import json
import pandas as pd
from abc import ABC, abstractmethod
from pathlib import Path
from typing import List

class TableStorage(ABC):
    @abstractmethod
    def save(self, grid: List[List[str]], file_path: Path):
        pass

    @abstractmethod
    def load(self, file_path: Path) -> str:
        pass

class MarkdownStorage(TableStorage):
    def save(self, grid: List[List[str]], file_path: Path):
        df = pd.DataFrame(grid)
        # Assuming the first row might be headers, or just use default
        md_content = df.to_markdown(index=False, header=False)
        file_path.with_suffix('.md').write_text(md_content, encoding='utf-8')

    def load(self, file_path: Path) -> str:
        return file_path.with_suffix('.md').read_text(encoding='utf-8')

class JSONStorage(TableStorage):
    def save(self, grid: List[List[str]], file_path: Path):
        with open(file_path.with_suffix('.json'), 'w', encoding='utf-8') as f:
            json.dump(grid, f, indent=4)

    def load(self, file_path: Path) -> str:
        with open(file_path.with_suffix('.json'), 'r', encoding='utf-8') as f:
            return json.dumps(json.load(f))

class HTMLStorage(TableStorage):
    def save(self, grid: List[List[str]], file_path: Path):
        df = pd.DataFrame(grid)
        html_content = df.to_html(index=False, header=False)
        file_path.with_suffix('.html').write_text(html_content, encoding='utf-8')

    def load(self, file_path: Path) -> str:
        return file_path.with_suffix('.html').read_text(encoding='utf-8')

class XMLStorage(TableStorage):
    def save(self, grid: List[List[str]], file_path: Path):
        df = pd.DataFrame(grid)
        xml_content = df.to_xml(index=False)
        file_path.with_suffix('.xml').write_text(xml_content, encoding='utf-8')

    def load(self, file_path: Path) -> str:
        return file_path.with_suffix('.xml').read_text(encoding='utf-8')

def get_storage(format_type: str) -> TableStorage:
    formats = {
        'md': MarkdownStorage(),
        'json': JSONStorage(),
        'html': HTMLStorage(),
        'xml': XMLStorage()
    }
    return formats.get(format_type.lower(), MarkdownStorage())
