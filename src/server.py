import setproctitle
import asyncio
import threading
import time
import shutil
import subprocess
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
from starlette.middleware.base import BaseHTTPMiddleware
from pydantic import BaseModel
import uvicorn
from pathlib import Path
from daz_agent_sdk import agent, Tier
from daz_agent_sdk.conversation import Conversation

PORT = 8766
BASE_DIR = Path(__file__).parent.parent
WATCH_DIR = BASE_DIR / "static"
MODELS_DIR = BASE_DIR / "local" / "models"
EXAMPLES_DIR = BASE_DIR / "examples"
DEFAULT_FILE = "default.js"
LIBRARY_SPEC_PATH = BASE_DIR / "static" / "cad-library-spec.md"

# global state for agent
agent_conversation: Conversation | None = None


# ##################################################################
# load library spec
# reads the cad library spec for the agent system prompt
def load_library_spec() -> str:
    if LIBRARY_SPEC_PATH.exists():
        return LIBRARY_SPEC_PATH.read_text()
    return "CAD library for creating 3D shapes using Workplane and Assembly classes."


# ##################################################################
# get system prompt
# creates the system prompt for the cad assistant agent
def get_system_prompt() -> str:
    library_spec = load_library_spec()
    return f"""You are an expert CAD assistant that helps users create and modify 3D models.

You work with a JavaScript CAD library. The user's code is in a .js file that you can read and modify.

IMPORTANT RULES:
1. When asked to modify the model, edit the actual .js file directly using the Write tool
2. Always preserve the overall structure: define shapes, combine them, set result variable
3. The file must end with `result;` to return the final shape
4. Use the Read tool to see the current file contents before making changes
5. Make minimal, targeted changes - don't rewrite the entire file unless necessary
6. After editing, briefly explain what you changed

Here is the CAD library specification:

{library_spec}
"""


# global state for hot reload
reload_event = asyncio.Event()
last_change_time = 0.0
DEBOUNCE_SECONDS = 0.5


# ##################################################################
# file watcher
# watches static directory for changes and triggers reload events
class FileWatcher:
    def __init__(self, watch_path: Path, debounce: float = 0.5):
        self.watch_path = watch_path
        self.debounce = debounce
        self.last_trigger = 0.0
        self.running = False
        self.file_times: dict[str, float] = {}
        self._init_file_times()

    def _init_file_times(self):
        for f in self.watch_path.rglob("*"):
            if f.is_file():
                self.file_times[str(f)] = f.stat().st_mtime

    def check_changes(self) -> bool:
        changed = False
        current_files = set()

        for f in self.watch_path.rglob("*"):
            if f.is_file():
                path_str = str(f)
                current_files.add(path_str)
                mtime = f.stat().st_mtime

                if path_str not in self.file_times:
                    self.file_times[path_str] = mtime
                    changed = True
                elif self.file_times[path_str] != mtime:
                    self.file_times[path_str] = mtime
                    changed = True

        # check for deleted files
        deleted = set(self.file_times.keys()) - current_files
        if deleted:
            for d in deleted:
                del self.file_times[d]
            changed = True

        return changed

    def run(self, loop: asyncio.AbstractEventLoop):
        global last_change_time
        self.running = True
        while self.running:
            if self.check_changes():
                now = time.time()
                if now - self.last_trigger > self.debounce:
                    self.last_trigger = now
                    last_change_time = now
                    loop.call_soon_threadsafe(reload_event.set)
            time.sleep(0.2)

    def stop(self):
        self.running = False


file_watcher: FileWatcher | None = None
watcher_thread: threading.Thread | None = None


# ##################################################################
# start file watcher
# initializes the file watcher in a background thread
def start_file_watcher():
    global file_watcher, watcher_thread
    loop = asyncio.get_event_loop()
    file_watcher = FileWatcher(WATCH_DIR)
    watcher_thread = threading.Thread(target=file_watcher.run, args=(loop,), daemon=True)
    watcher_thread.start()


# ##################################################################
# setup models directory
# creates models directory and copies example files if needed
def setup_models_directory():
    MODELS_DIR.mkdir(parents=True, exist_ok=True)

    if EXAMPLES_DIR.exists():
        for example_file in EXAMPLES_DIR.glob("*.js"):
            target = MODELS_DIR / example_file.name
            if not target.exists():
                shutil.copy(example_file, target)


# ##################################################################
# init git repo
# initializes git repo in models directory if not already initialized
def init_git_repo():
    git_dir = MODELS_DIR / ".git"
    if not git_dir.exists():
        subprocess.run(["git", "init"], cwd=MODELS_DIR, capture_output=True)
        # create initial commit with all existing files
        subprocess.run(["git", "add", "-A"], cwd=MODELS_DIR, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "Initial commit"],
            cwd=MODELS_DIR,
            capture_output=True
        )


# ##################################################################
# generate commit message
# uses claude haiku to generate a commit message from the diff
async def generate_commit_message(filename: str) -> str:
    # get the diff for this file
    result = subprocess.run(
        ["git", "diff", "--", filename],
        cwd=MODELS_DIR,
        capture_output=True,
        text=True
    )
    diff = result.stdout

    # if no diff (new file), get the file content
    if not diff:
        result = subprocess.run(
            ["git", "diff", "--cached", "--", filename],
            cwd=MODELS_DIR,
            capture_output=True,
            text=True
        )
        diff = result.stdout

    if not diff:
        # file might be untracked, just use a simple message
        return f"Add {filename}"

    # truncate diff if too long
    diff = diff[:5000]

    prompt = f"""Write a brief git commit message for this CAD model change.
The file is: {filename}

Requirements:
- Use imperative mood (e.g., "Add hole to base", "Increase height")
- Be concise (under 50 characters if possible)
- Focus on what changed in the 3D model, not code details
- Return ONLY the commit message, nothing else

Diff:
{diff}"""

    try:
        response = await agent.ask(prompt, tier=Tier.LOW)
        return response.text.strip() or f"Update {filename}"
    except Exception as e:
        # daz_agent_sdk failed - fall back to simple message
        print(f"[auto-commit] agent.ask error, using fallback message: {e}")
        return f"Update {filename}"


# ##################################################################
# commit changes
# stages and commits changes to a file with AI-generated message
async def commit_changes(filename: str):
    try:
        # check if there are changes to commit
        result = subprocess.run(
            ["git", "status", "--porcelain", "--", filename],
            cwd=MODELS_DIR,
            capture_output=True,
            text=True
        )
        if not result.stdout.strip():
            return  # no changes

        # stage the file
        subprocess.run(["git", "add", "--", filename], cwd=MODELS_DIR, capture_output=True)

        # generate commit message
        message = await generate_commit_message(filename)

        # commit
        subprocess.run(
            ["git", "commit", "-m", message],
            cwd=MODELS_DIR,
            capture_output=True
        )
        print(f"[auto-commit] Committed {filename}: {message}")
    except Exception as e:
        # Log but don't propagate - this is a background task
        print(f"[auto-commit] Failed to commit {filename}: {e}")


# ##################################################################
# lifespan
# manages startup and shutdown events for the application
@asynccontextmanager
async def lifespan(_app: FastAPI):
    global agent_conversation
    setup_models_directory()
    init_git_repo()
    start_file_watcher()
    agent_conversation = agent.conversation(
        "cad-assistant",
        tier=Tier.HIGH,
        system=get_system_prompt(),
    )
    await agent_conversation.__aenter__()
    yield
    if file_watcher:
        file_watcher.stop()
    if agent_conversation:
        await agent_conversation.__aexit__(None, None, None)
        agent_conversation = None


app = FastAPI(title="CAD Editor", lifespan=lifespan)


# ##################################################################
# no-cache middleware
# prevents browser caching of static files during development
class NoCacheMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        # Add no-cache headers for static files
        if request.url.path.startswith("/static"):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response


app.add_middleware(NoCacheMiddleware)

# mount static files for javascript and css assets
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

# mount examples directory for demo files
app.mount("/examples", StaticFiles(directory=BASE_DIR / "examples"), name="examples")


# ##################################################################
# root endpoint
# serves the main cad editor page with monaco and three.js
@app.get("/")
async def root():
    return FileResponse(BASE_DIR / "static" / "editor.html")


# ##################################################################
# init test endpoint
# serves the opencascade initialization test page
@app.get("/init-test")
async def init_test():
    return FileResponse(BASE_DIR / "static" / "index.html")


# ##################################################################
# performance test endpoint
# serves the performance testing page for benchmarking operations
@app.get("/perf-test")
async def perf_test():
    return FileResponse(BASE_DIR / "static" / "perf-test.html")


# ##################################################################
# health endpoint
# returns simple status for health checks and test fixtures
@app.get("/health")
async def health():
    return {"status": "ok"}


# ##################################################################
# favicon endpoint
# returns SVG favicon for the CAD editor
@app.get("/favicon.ico")
async def favicon():
    return FileResponse(BASE_DIR / "static" / "favicon-32.png", media_type="image/png")


# ##################################################################
# pydantic model for file save request
class FileSaveRequest(BaseModel):
    content: str


# ##################################################################
# pydantic model for chat message request
class ChatMessageRequest(BaseModel):
    message: str
    current_file: str
    current_code: str


# ##################################################################
# get model file
# loads a model file from the models directory
@app.get("/api/models/{filename}")
async def get_model(filename: str):
    if not filename.endswith(".js"):
        raise HTTPException(status_code=400, detail="Only .js files allowed")

    safe_name = Path(filename).name
    file_path = MODELS_DIR / safe_name

    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {filename}")

    content = file_path.read_text()
    mtime = file_path.stat().st_mtime
    return {"filename": safe_name, "content": content, "mtime": mtime}


# ##################################################################
# get model file modification time
# returns only the modification time for polling
@app.get("/api/models/{filename}/mtime")
async def get_model_mtime(filename: str):
    if not filename.endswith(".js"):
        raise HTTPException(status_code=400, detail="Only .js files allowed")

    safe_name = Path(filename).name
    file_path = MODELS_DIR / safe_name

    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {filename}")

    mtime = file_path.stat().st_mtime
    return {"filename": safe_name, "mtime": mtime}


# ##################################################################
# save model file
# saves content to a model file in the models directory
@app.post("/api/models/{filename}")
async def save_model(filename: str, request: FileSaveRequest):
    if not filename.endswith(".js"):
        raise HTTPException(status_code=400, detail="Only .js files allowed")

    safe_name = Path(filename).name
    file_path = MODELS_DIR / safe_name

    file_path.write_text(request.content)

    # commit changes with AI-generated message
    asyncio.create_task(commit_changes(safe_name))

    return {"filename": safe_name, "saved": True}


# ##################################################################
# list model files
# returns list of available model files
@app.get("/api/models")
async def list_models():
    files = sorted([f.name for f in MODELS_DIR.glob("*.js")])
    return {"files": files, "default": DEFAULT_FILE}


# ##################################################################
# reset model file
# restores a model file to its original template from examples
@app.post("/api/models/{filename}/reset")
async def reset_model(filename: str):
    if not filename.endswith(".js"):
        raise HTTPException(status_code=400, detail="Only .js files allowed")

    safe_name = Path(filename).name
    template_path = EXAMPLES_DIR / safe_name

    if not template_path.exists():
        raise HTTPException(status_code=404, detail="No template exists for this file")

    template_content = template_path.read_text()
    target_path = MODELS_DIR / safe_name
    target_path.write_text(template_content)

    return {
        "filename": safe_name,
        "content": template_content,
        "mtime": target_path.stat().st_mtime,
        "reset": True
    }


# ##################################################################
# check if template exists
# returns whether a file has a resettable template
@app.get("/api/models/{filename}/has-template")
async def has_template(filename: str):
    if not filename.endswith(".js"):
        raise HTTPException(status_code=400, detail="Only .js files allowed")

    safe_name = Path(filename).name
    template_path = EXAMPLES_DIR / safe_name

    return {"has_template": template_path.exists()}


# ##################################################################
# chat message endpoint
# sends a message to the cad assistant agent and returns the response
@app.post("/api/chat/message")
async def chat_message(request: ChatMessageRequest):
    global agent_conversation
    safe_name = Path(request.current_file).name
    file_path = MODELS_DIR / safe_name

    # save current code to file before agent processes (in case it needs to read it)
    file_path.write_text(request.current_code)
    original_content = request.current_code

    # build the prompt with context - include full path for agent to use
    full_path = str(file_path.absolute())
    prompt = f"""The user is editing the CAD model file at: {full_path}

User's request: {request.message}

Please help them modify the CAD model as requested. Use the Read tool to see the current file contents, then use Write or Edit to make changes."""

    # send message and collect response
    try:
        if agent_conversation is None:
            agent_conversation = agent.conversation(
                "cad-assistant",
                tier=Tier.HIGH,
                system=get_system_prompt(),
            )
            await agent_conversation.__aenter__()
        result = await agent_conversation.say(prompt)
        response_text = result.text
    except Exception as e:
        return {
            "response": f"Error communicating with assistant: {str(e)}",
            "file_changed": False,
            "new_content": None
        }

    # check if file was changed by agent
    file_changed = False
    new_content = None
    if file_path.exists():
        current_content = file_path.read_text()
        if current_content != original_content:
            file_changed = True
            new_content = current_content

    return {
        "response": response_text,
        "file_changed": file_changed,
        "new_content": new_content
    }


# ##################################################################
# hot reload sse endpoint
# streams server-sent events when files change for browser hot reload
@app.get("/hot-reload")
async def hot_reload():
    async def event_stream():
        global last_change_time
        client_time = 0.0

        while True:
            try:
                await asyncio.wait_for(reload_event.wait(), timeout=30.0)
                reload_event.clear()

                if last_change_time > client_time:
                    client_time = last_change_time
                    yield "data: reload\n\n"
            except asyncio.TimeoutError:
                # send keepalive
                yield ": keepalive\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


# ##################################################################
# model path endpoint (must be last to avoid capturing other routes)
# serves editor for a specific model via path (e.g., /anker_holder)
# frontend reads model name from path and loads it
@app.get("/{model_name}")
async def model_path(model_name: str):
    # Exclude paths that look like API endpoints, static files, or special routes
    excluded_prefixes = ("api", "static", "hot-reload", "health", "init-test", "perf-test")
    if model_name.startswith(excluded_prefixes):
        raise HTTPException(status_code=404, detail="Not found")

    # Only serve editor.html for model-like paths (no dots except .js extension)
    # This prevents capturing paths like favicon.ico or other static files
    if "." in model_name and not model_name.endswith(".js"):
        raise HTTPException(status_code=404, detail="Not found")

    return FileResponse(BASE_DIR / "static" / "editor.html")


# ##################################################################
# main
# starts the uvicorn server with configured host and port
def main():
    setproctitle.setproctitle("cad-editor-server")
    uvicorn.run(app, host="127.0.0.1", port=PORT)


# ##################################################################
# entry point
# standard python dispatch for main
if __name__ == "__main__":
    main()
