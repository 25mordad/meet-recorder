"""Find the main process of a browser so its whole process tree can be captured."""


def normalize_name(name, windows=True):
    name = name.lower()
    if windows and not name.endswith(".exe"):
        name += ".exe"
    return name


def find_root_pid(processes, name):
    """processes: iterable of (pid, ppid, name, create_time).

    Chrome runs many chrome.exe processes; the audio comes from a child of the main
    browser process. The main one is the chrome.exe whose parent is not chrome.exe.
    If there are several (e.g. two separate browser instances), the oldest wins.
    """
    name = name.lower()
    matching = [p for p in processes if p[2].lower() == name]
    pids = {p[0] for p in matching}
    roots = [p for p in matching if p[1] not in pids]
    if not roots:
        return None
    return min(roots, key=lambda p: p[3])[0]


def running_processes():
    import psutil
    result = []
    for p in psutil.process_iter(["pid", "ppid", "name", "create_time"]):
        info = p.info
        if info["name"]:
            result.append((info["pid"], info["ppid"], info["name"], info["create_time"] or 0.0))
    return result
