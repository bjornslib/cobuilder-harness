#!/usr/bin/env python3
"""
Claude Code Statusline Analyzer
Analyzes conversation context using Groq API with proper async handling
"""

import os
import sys
import json
import asyncio
import aiohttp
from pathlib import Path
from typing import Dict, Optional, Tuple
import time

# Configuration
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
CACHE_TTL = 30  # seconds
CACHE_DIR = Path.home() / ".claude" / "statusline_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

class StatuslineAnalyzer:
    def __init__(self, session_data: Dict):
        self.session_id = session_data.get("session_id", "current-session")
        self.current_dir = session_data.get("workspace", {}).get("current_dir", os.getcwd())
        self.model_name = session_data.get("model", {}).get("display_name", "Claude Code")
        self.groq_api_key = self._load_api_key()
        
    def _load_api_key(self) -> Optional[str]:
        """Load GROQ API key from environment or .env file"""
        # Check environment first
        api_key = os.environ.get("GROQ_API_KEY")
        
        if not api_key:
            # Try to load from project .env files
            env_paths = [
                Path(self.current_dir) / ".env",  # Root directory .env
                Path(self.current_dir) / "my-project-backend" / ".env",
                Path(self.current_dir).parent / "my-project-backend" / ".env",
            ]
            
            for env_path in env_paths:
                if env_path.exists():
                    try:
                        with open(env_path, 'r') as f:
                            for line in f:
                                if line.startswith("GROQ_API_KEY="):
                                    api_key = line.split("=", 1)[1].strip().strip('"').strip("'")
                                    break
                    except Exception:
                        pass
                
                if api_key:
                    break
        
        return api_key
    
    def _get_cache_key(self) -> str:
        """Generate cache key based on session and time window"""
        time_window = int(time.time() / CACHE_TTL) * CACHE_TTL
        return f"{self.session_id}_{time_window}"
    
    def _get_cached_result(self) -> Optional[Dict]:
        """Check if we have a valid cached result"""
        cache_file = CACHE_DIR / f"{self._get_cache_key()}.json"
        
        if cache_file.exists():
            try:
                with open(cache_file, 'r') as f:
                    return json.load(f)
            except Exception:
                pass
        
        return None
    
    def _save_to_cache(self, result: Dict):
        """Save result to cache"""
        cache_file = CACHE_DIR / f"{self._get_cache_key()}.json"
        try:
            with open(cache_file, 'w') as f:
                json.dump(result, f)
        except Exception:
            pass
        
        # Clean old cache files
        try:
            cutoff_time = time.time() - 300  # 5 minutes
            for cache_file in CACHE_DIR.glob("*.json"):
                if cache_file.stat().st_mtime < cutoff_time:
                    cache_file.unlink()
        except Exception:
            pass
    
    def _get_conversation_history(self) -> Optional[str]:
        """Load recent conversation from JSONL file"""
        # Convert current directory to Claude's project format
        project_dir = self.current_dir.replace("/", "-")
        claude_projects_dir = Path.home() / ".claude" / "projects" / project_dir
        
        if not claude_projects_dir.exists():
            return None
        
        # Find the most recent JSONL file
        jsonl_files = list(claude_projects_dir.glob("*.jsonl"))
        if not jsonl_files:
            return None
        
        jsonl_file = max(jsonl_files, key=lambda f: f.stat().st_mtime)
        
        # Extract last 10-15 messages
        messages = []
        try:
            with open(jsonl_file, 'r') as f:
                lines = f.readlines()[-15:]  # Get last 15 lines
                
                for line in lines:
                    try:
                        data = json.loads(line)
                        if data.get("type") in ["user", "assistant"]:
                            msg_text = data.get("message", "")
                            if isinstance(msg_text, str):
                                msg_text = msg_text[:200]
                            messages.append(f"{data['type']}: {msg_text}")
                    except Exception:
                        continue
                
                # Keep only last 10 messages
                messages = messages[-10:]
        except Exception:
            return None
        
        return "\n".join(messages) if messages else None
    
    async def analyze_with_groq(self, messages: str) -> Dict:
        """Call Groq API to analyze conversation"""
        if not self.groq_api_key:
            return {"error": "No API key"}
        
        prompt = f"""Analyze this conversation and extract in JSON format:
1. current_goal: What is the user trying to achieve? (max 50 chars)
2. last_action: What was the last significant action taken? (max 40 chars)
3. input_needed: What input/decision is needed from user? Options: 'Ready', 'Decision needed', 'Error resolution', 'Task complete', 'Feedback required', or custom short status (max 20 chars)

Messages:
{messages}

Respond ONLY with valid JSON like: {{"current_goal": "...", "last_action": "...", "input_needed": "..."}}"""
        
        headers = {
            "Authorization": f"Bearer {self.groq_api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": "llama-3.3-70b-versatile",
            "messages": [
                {"role": "system", "content": "You are a concise analyzer. Output only valid JSON."},
                {"role": "user", "content": prompt}
            ],
            "max_tokens": 100,
            "temperature": 0.1,
            "stream": False
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    GROQ_API_URL,
                    headers=headers,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                        
                        # Try to parse the JSON response
                        try:
                            result = json.loads(content)
                            return result
                        except json.JSONDecodeError:
                            return {"error": "Invalid JSON response"}
                    else:
                        return {"error": f"API error: {response.status}"}
        except asyncio.TimeoutError:
            return {"error": "Timeout"}
        except Exception as e:
            return {"error": str(e)}
    
    async def get_status_info(self) -> Tuple[str, str, str]:
        """Get current goal, last action, and input needed"""
        # Default values
        current_goal = "Initializing..."
        last_action = "No recent changes"
        input_needed = "Ready"
        
        # Check cache first
        cached = self._get_cached_result()
        if cached and "error" not in cached:
            return (
                cached.get("current_goal", current_goal),
                cached.get("last_action", last_action),
                cached.get("input_needed", input_needed)
            )
        
        # Get conversation history
        messages = self._get_conversation_history()
        
        if messages and self.groq_api_key:
            # Call Groq API
            result = await self.analyze_with_groq(messages)
            
            if "error" not in result:
                # Save to cache
                self._save_to_cache(result)
                
                current_goal = result.get("current_goal", current_goal)[:50]
                last_action = result.get("last_action", last_action)[:40]
                input_needed = result.get("input_needed", input_needed)[:20]
        elif messages:
            # Fallback to simple extraction without Groq
            lines = messages.split("\n")
            for line in reversed(lines):
                if line.startswith("user:") and current_goal == "Initializing...":
                    current_goal = line[5:55]
                elif line.startswith("assistant:") and last_action == "No recent changes":
                    text = line[10:]
                    if any(word in text.lower() for word in ["created", "updated", "fixed", "added"]):
                        last_action = text[:40]
        
        # Check TodoWrite status
        todos_file = Path(self.current_dir) / ".claude" / "current_todos.json"
        if todos_file.exists():
            try:
                with open(todos_file, 'r') as f:
                    todos_data = json.load(f)
                    for todo in todos_data.get("todos", []):
                        if todo.get("status") == "in_progress":
                            current_goal = todo.get("activeForm", current_goal)[:50]
                            break
            except Exception:
                pass
        
        return current_goal, last_action, input_needed
    
    def format_statusline(self, current_goal: str, last_action: str, input_needed: str) -> str:
        """Format the statusline output with colors"""
        # Color codes
        DIM = '\033[2m'
        RESET = '\033[0m'
        CYAN = '\033[0;36m'
        BLUE = '\033[0;34m'
        GREEN = '\033[0;32m'
        YELLOW = '\033[1;33m'
        MAGENTA = '\033[0;35m'
        RED = '\033[0;31m'
        WHITE = '\033[1;37m'
        
        # Build statusline
        output = f"{DIM}[{RESET}{CYAN}{self.model_name}{RESET}{DIM}]{RESET} "
        
        # Show Groq indicator if API is active
        if self.groq_api_key:
            output += f"{DIM}🧠{RESET} "
        
        # Current goal
        output += f"{BLUE}Goal:{RESET} {current_goal}"
        output += f" {DIM}|{RESET} "
        
        # Last action
        if last_action != "No recent changes":
            output += f"{GREEN}Last:{RESET} {last_action}"
        else:
            output += f"{DIM}Last:{RESET} {DIM}{last_action}{RESET}"
        
        output += f" {DIM}|{RESET} "
        
        # Input status
        if "Decision" in input_needed or "Feedback" in input_needed:
            output += f"{MAGENTA}⚡{RESET} {input_needed}"
        elif "Error" in input_needed:
            output += f"{RED}⚠{RESET} {input_needed}"
        elif "complete" in input_needed.lower():
            output += f"{GREEN}✓{RESET} {input_needed}"
        elif "Ready" in input_needed:
            output += f"{WHITE}•{RESET} {input_needed}"
        else:
            output += f"{YELLOW}⏳{RESET} {input_needed}"
        
        return output

async def main():
    """Main entry point"""
    # Read JSON input from stdin
    try:
        input_data = json.loads(sys.stdin.read())
    except Exception:
        input_data = {}
    
    # Create analyzer
    analyzer = StatuslineAnalyzer(input_data)
    
    # Get status info
    current_goal, last_action, input_needed = await analyzer.get_status_info()
    
    # Format and print statusline
    statusline = analyzer.format_statusline(current_goal, last_action, input_needed)
    print(statusline, end='')

if __name__ == "__main__":
    asyncio.run(main())