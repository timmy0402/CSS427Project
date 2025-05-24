# jsonbuffer.py

_shared_data = None

def get_shared_data():
    global _shared_data
    if _shared_data is None:
        from multiprocessing import Manager
        manager = Manager()
        _shared_data = manager.list()
    return _shared_data
