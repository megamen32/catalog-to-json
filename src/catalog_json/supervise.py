"""Per-call Linux subreaper: an exited worker cannot orphan its MCP sessions."""
import argparse,asyncio,ctypes,os,subprocess,sys,signal
from .processes import OwnedProcessTree


class Terminated(BaseException):pass


def terminate(signum,frame):raise Terminated()


def main():
    p=argparse.ArgumentParser();p.add_argument('--deadline',type=int,required=True);p.add_argument('command',nargs=argparse.REMAINDER)
    args=p.parse_args();command=args.command[1:] if args.command[:1]==['--'] else args.command
    if not command or args.deadline<=0:raise ValueError('Supervisor requires a command and finite deadline')
    if not sys.platform.startswith('linux'):raise RuntimeError('Parallel stages require Linux process supervision; native parsers may still execute on a Mac')
    libc=ctypes.CDLL(None,use_errno=True)
    if libc.prctl(36,1,0,0,0)!=0:raise OSError(ctypes.get_errno(),'Cannot enable own child subreaper')
    signal.signal(signal.SIGTERM,terminate)
    # This supervisor belongs to one role call, never a shared service or another
    # provider worker. Orphans in separate sessions are reparented here.
    tree=OwnedProcessTree(os.getpid());child=subprocess.Popen(command)
    try:
        try:code=child.wait(timeout=args.deadline)
        except subprocess.TimeoutExpired:code=124
        except (Terminated,KeyboardInterrupt):code=143
    finally:asyncio.run(tree.cleanup(exclude_pid=os.getpid()))
    return code


if __name__=='__main__':raise SystemExit(main())
