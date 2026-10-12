"""Bounded cleanup of registered own descendants, including separate MCP sessions."""
import asyncio
import psutil


class OwnedProcessTree:
    def __init__(self,pid):self.processes={pid:psutil.Process(pid)}

    def capture(self):
        for parent in list(self.processes.values()):
            try:
                for child in parent.children(recursive=True):self.processes.setdefault(child.pid,child)
            except psutil.Error:pass

    async def watch(self):
        while True:self.capture();await asyncio.sleep(.1)

    async def cleanup(self,exclude_pid=None):
        self.capture()
        live=[]
        for process in reversed(list(self.processes.values())):
            if process.pid==exclude_pid:continue
            try:
                if process.is_running() and process.status()!=psutil.STATUS_ZOMBIE:process.terminate();live.append(process)
            except psutil.Error:pass
        _,alive=await asyncio.to_thread(psutil.wait_procs,live,timeout=5)
        self.capture()
        for process in list(self.processes.values()):
            if process.pid==exclude_pid:continue
            try:
                if process.is_running() and process.status()!=psutil.STATUS_ZOMBIE:process.kill()
            except psutil.Error:pass
        await asyncio.to_thread(psutil.wait_procs,alive,timeout=2)
