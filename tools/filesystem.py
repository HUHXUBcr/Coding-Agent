import os

class FileSystemTool:
    def __init__(self, base_dir):
        self.base_dir = base_dir
        os.makedirs(base_dir, exist_ok=True)

    def resolve(self, relative):
        full = os.path.join(self.base_dir, relative)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        return full

    def write_file(self, path, content):
        with open(path, "w", encoding="utf8") as f:
            f.write(content)

    def read_file(self, path):
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
