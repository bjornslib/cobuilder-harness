# Research: Dead Worker Detection, ThreadPoolExecutor Future Lifecycle, and Python Process Management Patterns

## Executive Summary

This research document explores patterns and techniques for detecting dead workers, managing ThreadPoolExecutor futures, and implementing robust process management in Python applications. The focus is on scenarios similar to a pipeline runner that dispatches workers via AgentSDK and needs to detect when those workers die unexpectedly without writing completion signals.

## 1. ThreadPoolExecutor Future Lifecycle Management

### 1.1 Basic Future Patterns

```python
from concurrent.futures import ThreadPoolExecutor, Future, as_completed
import threading
import time
from typing import Dict, Callable, Any

class WorkerManager:
    def __init__(self):
        self.executor = ThreadPoolExecutor(max_workers=4)
        self.active_futures: Dict[str, Future] = {}
        self.dispatch_times: Dict[str, float] = {}

    def submit_worker(self, node_id: str, worker_func: Callable, *args) -> Future:
        """Submit a worker function and track its future."""
        future = self.executor.submit(worker_func, *args)
        self.active_futures[node_id] = future
        self.dispatch_times[node_id] = time.time()
        return future

    def check_worker_liveness(self) -> None:
        """Check for completed futures and detect dead workers."""
        for node_id, future in list(self.active_futures.items()):
            if future.done():
                # Future has completed - check if it succeeded or failed
                try:
                    result = future.result(timeout=0.01)  # Non-blocking since we know it's done
                    print(f"Worker {node_id} completed successfully with result: {result}")
                except Exception as e:
                    print(f"Worker {node_id} failed with exception: {e}")
                    # This is where we'd write a failure signal
                    self.handle_worker_failure(node_id, str(e))

                # Remove from active tracking
                del self.active_futures[node_id]
                if node_id in self.dispatch_times:
                    del self.dispatch_times[node_id]

    def handle_worker_failure(self, node_id: str, error: str) -> None:
        """Handle a failed worker by writing an appropriate signal."""
        # Write failure signal to indicate the worker died
        print(f"Writing failure signal for {node_id}: {error}")
```

### 1.2 Advanced Future Lifecycle with Callbacks

```python
import concurrent.futures
from concurrent.futures import Future
import logging

def add_future_callbacks(future: Future, node_id: str, callback_handler):
    """Add callbacks to handle future completion events."""

    def success_callback(fut):
        if not fut.exception():
            result = fut.result()
            logging.info(f"Worker {node_id} completed successfully: {result}")
            callback_handler.on_worker_success(node_id, result)

    def failure_callback(fut):
        if fut.exception():
            exception = fut.exception()
            logging.error(f"Worker {node_id} failed with: {exception}")
            callback_handler.on_worker_failure(node_id, exception)

    future.add_done_callback(success_callback)
    future.add_done_callback(failure_callback)

class CallbackHandler:
    def on_worker_success(self, node_id: str, result: Any):
        # Handle successful worker completion
        pass

    def on_worker_failure(self, node_id: str, exception: Exception):
        # Handle worker failure - write failure signal
        pass
```

## 2. Dead Worker Detection Patterns

### 2.1 Timeout-Based Detection

```python
import time
from typing import Dict, Set
import psutil  # Requires: pip install psutil

class DeadWorkerDetector:
    def __init__(self, default_timeout: int = 900):  # 15 minutes default
        self.default_timeout = default_timeout
        self.dispatch_times: Dict[str, float] = {}
        self.active_workers: Dict[str, Dict] = {}  # node_id -> worker_info

    def register_worker(self, node_id: str, pid: int = None, process_handle = None):
        """Register a new worker with its dispatch time and process info."""
        self.dispatch_times[node_id] = time.time()
        self.active_workers[node_id] = {
            'dispatch_time': time.time(),
            'pid': pid,
            'process_handle': process_handle,
            'last_check': time.time()
        }

    def detect_dead_workers(self) -> Set[str]:
        """Detect workers that have exceeded timeout or died."""
        dead_workers = set()
        current_time = time.time()

        for node_id, worker_info in self.active_workers.items():
            elapsed = current_time - worker_info['dispatch_time']

            # Check timeout
            timeout = int(os.getenv('WORKER_TIMEOUT', str(self.default_timeout)))
            if elapsed > timeout:
                dead_workers.add(node_id)
                continue

            # Check process liveness if PID is available
            if worker_info['pid']:
                try:
                    # Check if process is still running
                    proc = psutil.Process(worker_info['pid'])
                    if not proc.is_running():
                        dead_workers.add(node_id)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    # Process doesn't exist or we can't access it
                    dead_workers.add(node_id)

        return dead_workers

    def cleanup_dead_workers(self, dead_workers: Set[str]) -> None:
        """Clean up dead workers and write failure signals."""
        for node_id in dead_workers:
            if node_id in self.active_workers:
                worker_info = self.active_workers[node_id]
                elapsed = time.time() - worker_info['dispatch_time']

                # Write failure signal
                self.write_failure_signal(
                    node_id,
                    f"Worker timed out after {elapsed:.0f}s (limit: {self.default_timeout}s)"
                )

                # Remove from tracking
                del self.active_workers[node_id]
                if node_id in self.dispatch_times:
                    del self.dispatch_times[node_id]

    def write_failure_signal(self, node_id: str, reason: str):
        """Write a failure signal to indicate the worker died."""
        # Implementation depends on specific pipeline runner signal format
        signal_payload = {
            "status": "error",
            "result": "fail",
            "reason": reason,
            "worker_crash": True,
            "timestamp": time.time()
        }
        print(f"Writing failure signal for {node_id}: {signal_payload}")
```

### 2.2 Future-State Monitoring

```python
from concurrent.futures import ThreadPoolExecutor, Future
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Dict, Any

class WorkerState(Enum):
    SUBMITTED = "submitted"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"

@dataclass
class WorkerInfo:
    node_id: str
    future: Future
    submitted_at: float
    state: WorkerState = WorkerState.SUBMITTED
    result: Optional[Any] = None
    exception: Optional[Exception] = None

class AdvancedWorkerTracker:
    def __init__(self, default_timeout: int = 900):
        self.default_timeout = default_timeout
        self.workers: Dict[str, WorkerInfo] = {}
        self.lock = threading.RLock()

    def track_worker(self, node_id: str, future: Future) -> WorkerInfo:
        """Track a new worker future."""
        with self.lock:
            worker_info = WorkerInfo(
                node_id=node_id,
                future=future,
                submitted_at=time.time()
            )
            self.workers[node_id] = worker_info
            return worker_info

    def update_worker_states(self) -> None:
        """Update states of all tracked workers."""
        current_time = time.time()
        timeout_threshold = self.default_timeout

        with self.lock:
            for node_id, worker_info in self.workers.items():
                if worker_info.state in [WorkerState.COMPLETED, WorkerState.FAILED, WorkerState.CANCELLED]:
                    continue

                # Check if future is done
                if worker_info.future.done():
                    try:
                        worker_info.result = worker_info.future.result(timeout=0.01)
                        worker_info.state = WorkerState.COMPLETED
                    except Exception as e:
                        worker_info.exception = e
                        worker_info.state = WorkerState.FAILED
                    continue

                # Check for timeout
                elapsed = current_time - worker_info.submitted_at
                if elapsed > timeout_threshold:
                    # Attempt to cancel the future
                    if worker_info.future.cancel():
                        worker_info.state = WorkerState.CANCELLED
                    else:
                        worker_info.state = WorkerState.TIMED_OUT

    def get_dead_workers(self) -> list:
        """Get list of workers that are in failed, timed_out, or cancelled states."""
        with self.lock:
            dead_workers = []
            for node_id, worker_info in self.workers.items():
                if worker_info.state in [WorkerState.FAILED, WorkerState.TIMED_OUT, WorkerState.CANCELLED]:
                    dead_workers.append((node_id, worker_info))
            return dead_workers

    def remove_worker(self, node_id: str) -> bool:
        """Remove a worker from tracking."""
        with self.lock:
            if node_id in self.workers:
                del self.workers[node_id]
                return True
            return False
```

## 3. AgentSDK Process Management

### 3.1 AgentSDK Worker Dispatch Pattern

Based on the context, Claude Code SDK workers likely run as subprocesses. Here's how to track them:

```python
import subprocess
import threading
import time
import json
import os
from pathlib import Path
from typing import Dict, Optional

class AgentSDKManager:
    def __init__(self, signal_dir: str):
        self.signal_dir = Path(signal_dir)
        self.active_processes: Dict[str, subprocess.Popen] = {}
        self.dispatch_times: Dict[str, float] = {}
        self.lock = threading.Lock()

    def dispatch_agent_worker(self, node_id: str, worker_args: list) -> Optional[subprocess.Popen]:
        """Dispatch an agent worker via SDK and track the process."""
        try:
            # Capture the start time
            start_time = time.time()

            # Launch the subprocess with specific command
            cmd = ["claude_code_sdk"] + worker_args
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,  # Line buffered
                universal_newlines=True
            )

            # Track the process
            with self.lock:
                self.active_processes[node_id] = process
                self.dispatch_times[node_id] = start_time

            return process

        except Exception as e:
            print(f"Failed to dispatch worker {node_id}: {e}")
            # Write immediate failure signal
            self._write_failure_signal(node_id, f"Dispatch failed: {str(e)}")
            return None

    def check_process_liveness(self) -> None:
        """Check for dead processes and write failure signals."""
        current_time = time.time()
        timeout = int(os.getenv("WORKER_SIGNAL_TIMEOUT", "900"))  # 15 min default

        with self.lock:
            # Make a copy to avoid modification during iteration
            processes_to_check = dict(self.active_processes)

        for node_id, process in processes_to_check.items():
            # Check if process has terminated
            return_code = process.poll()  # Non-blocking check

            # Check if process is dead without writing signal
            if return_code is not None:  # Process terminated
                # Check if corresponding signal file exists
                signal_file = self.signal_dir / f"{node_id}.json"
                if not signal_file.exists():
                    # Process died without writing signal
                    _, stderr_data = process.communicate()  # Get any error output

                    error_msg = f"Worker process died with exit code {return_code}"
                    if stderr_data:
                        error_msg += f": {stderr_data[:300]}"  # Limit length

                    self._write_failure_signal(node_id, error_msg)

                # Clean up tracking
                with self.lock:
                    if node_id in self.active_processes:
                        del self.active_processes[node_id]
                    if node_id in self.dispatch_times:
                        del self.dispatch_times[node_id]

            # Check for timeout
            else:
                dispatch_time = self.dispatch_times.get(node_id, current_time)
                if current_time - dispatch_time > timeout:
                    # Process is taking too long - terminate it
                    try:
                        process.terminate()
                        process.wait(timeout=5)  # Wait up to 5 seconds for graceful termination
                    except subprocess.TimeoutExpired:
                        # Force kill if it doesn't terminate gracefully
                        process.kill()

                    self._write_failure_signal(
                        node_id,
                        f"Worker timed out after {timeout}s"
                    )

                    # Clean up tracking
                    with self.lock:
                        if node_id in self.active_processes:
                            del self.active_processes[node_id]
                        if node_id in self.dispatch_times:
                            del self.dispatch_times[node_id]

    def _write_failure_signal(self, node_id: str, reason: str) -> None:
        """Write a failure signal when a worker dies."""
        signal_payload = {
            "status": "error",
            "result": "fail",
            "reason": reason,
            "worker_crash": True,
            "timestamp": time.time()
        }

        signal_path = self.signal_dir / f"{node_id}.json"
        try:
            with open(signal_path, 'w') as f:
                json.dump(signal_payload, f)
        except Exception as e:
            print(f"Failed to write failure signal for {node_id}: {e}")
```

## 4. Watchdog Pattern for File-Based Signal Detection

### 4.1 File System Monitoring

```python
import os
import time
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import threading

class SignalFileHandler(FileSystemEventHandler):
    def __init__(self, callback_func):
        super().__init__()
        self.callback = callback_func

    def on_created(self, event):
        if event.is_directory:
            return
        if event.src_path.endswith('.json'):
            self.callback(event.src_path)

    def on_modified(self, event):
        if event.is_directory:
            return
        if event.src_path.endswith('.json'):
            self.callback(event.src_path)

class SignalWatchdog:
    def __init__(self, signal_dir: str, signal_callback):
        self.signal_dir = Path(signal_dir)
        self.signal_callback = signal_callback
        self.observer = Observer()
        self.handler = SignalFileHandler(self._handle_signal_file)
        self.running = False

    def _handle_signal_file(self, file_path: str):
        """Handle a new or modified signal file."""
        try:
            with open(file_path, 'r') as f:
                signal_data = json.load(f)
            self.signal_callback(file_path, signal_data)
        except Exception as e:
            print(f"Error processing signal file {file_path}: {e}")

    def start(self):
        """Start monitoring the signal directory."""
        self.observer.schedule(self.handler, str(self.signal_dir), recursive=False)
        self.observer.start()
        self.running = True

    def stop(self):
        """Stop monitoring."""
        self.observer.stop()
        self.observer.join()
        self.running = False

# Alternative simpler polling approach
class SignalPoller:
    def __init__(self, signal_dir: str, check_interval: float = 2.0):
        self.signal_dir = Path(signal_dir)
        self.check_interval = check_interval
        self.processed_files = set()
        self.last_checks = {}
        self.running = False
        self.thread = None

    def start(self):
        """Start polling in a separate thread."""
        self.running = True
        self.thread = threading.Thread(target=self._poll_loop, daemon=True)
        self.thread.start()

    def stop(self):
        """Stop polling."""
        self.running = False
        if self.thread:
            self.thread.join()

    def _poll_loop(self):
        """Main polling loop."""
        while self.running:
            self._check_for_new_signals()
            time.sleep(self.check_interval)

    def _check_for_new_signals(self):
        """Check for new or modified signal files."""
        current_time = time.time()

        for signal_file in self.signal_dir.glob("*.json"):
            mtime = signal_file.stat().st_mtime

            # Check if file is new or has been modified since last check
            if signal_file not in self.last_checks or self.last_checks[signal_file] < mtime:
                try:
                    with open(signal_file, 'r') as f:
                        signal_data = json.load(f)

                    # Process the signal (implementation depends on pipeline runner needs)
                    self.process_signal(signal_file, signal_data)

                    # Update last check time
                    self.last_checks[signal_file] = mtime

                except Exception as e:
                    print(f"Error processing signal file {signal_file}: {e}")

    def process_signal(self, signal_file: Path, signal_data: dict):
        """Process an individual signal file - to be implemented by caller."""
        # This would call the pipeline runner's signal processing logic
        pass
```

## 5. Atomic Signal File Operations

### 5.1 Atomic Write Pattern

```python
import tempfile
import os
import json
from pathlib import Path

def atomic_write_signal(signal_path: Path, payload: dict) -> str:
    """
    Atomically write a signal file using the temp file + rename pattern.

    Args:
        signal_path: Path to the target signal file
        payload: Dictionary to serialize as JSON

    Returns:
        Path to the written file
    """
    # Add metadata for ordering and debugging
    import time
    import datetime

    payload["_seq"] = getattr(atomic_write_signal, '_sequence', 0) + 1
    setattr(atomic_write_signal, '_sequence', payload["_seq"])
    payload["_ts"] = datetime.datetime.utcnow().isoformat() + "Z"
    payload["_pid"] = os.getpid()

    # Create temporary file with unique name
    tmp_path = signal_path.with_suffix(f'.tmp.{os.getpid()}.{int(time.monotonic_ns())}')

    try:
        # Write to temporary file
        with open(tmp_path, 'w') as fh:
            json.dump(payload, fh, indent=2)
            fh.flush()  # Flush to OS buffer
            os.fsync(fh.fileno())  # Force OS to write to disk

        # Atomically rename (POSIX atomic operation)
        os.rename(str(tmp_path), str(signal_path))

        return str(signal_path)

    except Exception as e:
        # Clean up temp file if something went wrong
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except:
                pass  # Ignore cleanup errors
        raise e

def safe_read_signal(signal_path: Path) -> dict:
    """
    Safely read a signal file, handling corruption gracefully.

    Args:
        signal_path: Path to the signal file to read

    Returns:
        Parsed signal data dictionary
    """
    try:
        with open(signal_path, 'r') as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        # Log the error and quarantine the corrupted file
        print(f"Error reading signal file {signal_path}: {exc}")

        # Quarantine corrupted file
        quarantine_dir = signal_path.parent / "quarantine"
        quarantine_dir.mkdir(exist_ok=True)
        quarantined_path = quarantine_dir / f"corrupted_{signal_path.name}_{int(time.time())}"

        try:
            import shutil
            shutil.move(str(signal_path), str(quarantined_path))
            print(f"Quarantined corrupted signal file: {quarantined_path}")
        except Exception as move_exc:
            print(f"Failed to quarantine corrupted file: {move_exc}")

        raise exc
```

## 6. Integration Example for Pipeline Runner

```python
import os
import time
import threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import subprocess
import json

class RobustPipelineRunner:
    def __init__(self, signal_dir: str, max_workers: int = 4):
        self.signal_dir = Path(signal_dir)
        self.max_workers = max_workers
        self.executor = ThreadPoolExecutor(max_workers=max_workers)

        # Tracking structures
        self.active_workers = {}  # node_id -> process or future
        self.dispatch_times = {}  # node_id -> dispatch timestamp
        self.worker_pids = {}     # node_id -> process PID if applicable

        # Start monitoring thread
        self.monitoring = True
        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.monitor_thread.start()

    def dispatch_worker(self, node_id: str, worker_cmd: list):
        """Dispatch a worker and start tracking it."""
        try:
            # Launch the subprocess
            process = subprocess.Popen(
                worker_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )

            # Track the worker
            self.active_workers[node_id] = process
            self.dispatch_times[node_id] = time.time()
            self.worker_pids[node_id] = process.pid

        except Exception as e:
            # Write immediate failure signal
            self._write_failure_signal(node_id, f"Worker dispatch failed: {str(e)}")

    def _monitor_loop(self):
        """Background monitoring loop for dead workers."""
        while self.monitoring:
            self._check_worker_liveness()
            time.sleep(2)  # Check every 2 seconds

    def _check_worker_liveness(self):
        """Check all active workers for liveness."""
        timeout = int(os.getenv("WORKER_SIGNAL_TIMEOUT", "900"))  # 15 min default
        current_time = time.time()

        # Iterate over a copy to avoid modification during iteration
        for node_id in list(self.active_workers.keys()):
            if node_id not in self.active_workers:
                continue

            process = self.active_workers[node_id]

            # Check if process is still running
            return_code = process.poll()

            if return_code is not None:  # Process terminated
                # Check if signal file was written
                signal_path = self.signal_dir / f"{node_id}.json"
                if not signal_path.exists():
                    # Process died without writing signal - report failure
                    stderr, _ = process.communicate()  # Get error output
                    error_msg = f"Worker died with exit code {return_code}"
                    if stderr:
                        error_msg += f": {stderr[:500]}"

                    self._write_failure_signal(node_id, error_msg)

                # Remove from active tracking
                self.active_workers.pop(node_id, None)
                self.dispatch_times.pop(node_id, None)
                self.worker_pids.pop(node_id, None)

            # Check for timeout
            elif node_id in self.dispatch_times:
                elapsed = current_time - self.dispatch_times[node_id]
                if elapsed > timeout:
                    # Terminate the process
                    try:
                        process.terminate()
                        try:
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            process.kill()  # Force kill if not terminating
                    except Exception:
                        pass  # Process might already be dead

                    self._write_failure_signal(
                        node_id,
                        f"Worker timed out after {elapsed:.0f}s (limit: {timeout}s)"
                    )

                    # Remove from tracking
                    self.active_workers.pop(node_id, None)
                    self.dispatch_times.pop(node_id, None)
                    self.worker_pids.pop(node_id, None)

    def _write_failure_signal(self, node_id: str, reason: str):
        """Write a failure signal atomically."""
        signal_payload = {
            "status": "error",
            "result": "fail",
            "reason": reason,
            "worker_crash": True,
            "timestamp": time.time()
        }

        signal_path = self.signal_dir / f"{node_id}.json"
        try:
            atomic_write_signal(signal_path, signal_payload)
        except Exception as e:
            print(f"Failed to write failure signal for {node_id}: {e}")

    def stop_monitoring(self):
        """Stop the monitoring thread."""
        self.monitoring = False
        if self.monitor_thread.is_alive():
            self.monitor_thread.join()
        self.executor.shutdown(wait=True)
```

## 7. Best Practices Summary

### 7.1 Process Monitoring Best Practices
1. **Track process lifetimes**: Keep track of when workers are dispatched
2. **Use timeouts**: Implement configurable timeout mechanisms
3. **Graceful cleanup**: Attempt graceful shutdown before force-killing
4. **Error capture**: Capture stderr/stdout from failed processes
5. **Signal integrity**: Write failure signals when workers die unexpectedly

### 7.2 Future Management Best Practices
1. **Proactive checking**: Regularly check future.done() status
2. **Exception handling**: Handle both successful completion and exceptions
3. **Resource cleanup**: Remove completed futures from tracking structures
4. **Callback patterns**: Use callbacks for immediate notification of completion

### 7.3 File System Best Practices
1. **Atomic operations**: Use temp file + rename for atomic writes
2. **Corruption handling**: Quarantine corrupted files rather than silently ignoring
3. **Metadata inclusion**: Add sequence numbers and timestamps to signals
4. **Monitoring strategies**: Use either watchdog or polling, not both simultaneously

## 8. Key Takeaways

1. **Dead worker detection is critical** for long-running pipeline systems where workers may crash silently
2. **Timeout mechanisms** should be configurable and reasonable (typically 10-30 minutes depending on workload)
3. **Process monitoring** is more reliable than future monitoring when using subprocess-based workers (like AgentSDK)
4. **Signal integrity** is paramount - missing signals can cause pipeline nodes to hang indefinitely
5. **Atomic file operations** prevent corruption during concurrent writes
6. **Background monitoring** threads should run independently and not block main execution flow

This research demonstrates that dead worker detection requires a combination of process monitoring, timeout enforcement, and robust signal handling to ensure pipeline resilience.

## Implementation Status

| Epic | Status | Date | Commit |
|------|--------|------|--------|
| - | Remaining | - | - |
