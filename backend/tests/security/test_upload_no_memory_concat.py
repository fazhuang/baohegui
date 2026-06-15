"""安全测试 — 上传零全量内存拼接

覆盖：
- 上传代码中不存在 chunks 列表（bytes 列表收集）
- 不存在 b"".join(chunks) 全量拼接
- streaming write 路径存在
- upload_file 函数内 AST 结构级校验（分块读取、hash 更新、无全量读入）
- 严格验证 file.read(chunk_size)、hasher.update(chunk)、_os.write 在同一 while 内
"""

import ast
from pathlib import Path


class TestUploadNoFullMemoryConcat:
    """上传代码不应有全量内存拼接路径"""

    def _get_upload_source(self) -> str:
        upload_path = Path(__file__).resolve().parent.parent.parent / "app" / "api" / "upload.py"
        return upload_path.read_text(encoding="utf-8")

    def test_no_chunks_list_in_upload(self):
        """upload.py 不应包含 chunks: list[bytes] = [] 或类似全量收集"""
        source = self._get_upload_source()
        assert "chunks: list[bytes]" not in source, "不应有全量 chunks 列表声明"
        assert 'chunks.append(' not in source, "不应有 chunks.append() 全量收集"
        assert 'b"".join(chunks)' not in source, "不应有 b''.join(chunks) 全量拼接"

    def test_streaming_write_exists(self):
        """upload.py 应包含流式写临时文件的代码"""
        source = self._get_upload_source()
        assert "tempfile.mkstemp" in source or "tempfile.NamedTemporaryFile" in source, \
            "应有临时文件创建"
        assert "_os.write" in source or "tmp_fd" in source, \
            "应有流式写文件操作"
        assert "hasher.update(chunk)" in source or "hashlib.sha256" in source, \
            "应有滚动 hash"

    # ── AST helper ───────────────────────────────────────

    @staticmethod
    def _is_read_call(node: ast.Call) -> str | None:
        """Return 'chunked' | 'full' | None based on read() call."""
        if not isinstance(node.func, ast.Attribute):
            return None
        if node.func.attr != "read":
            return None
        return "chunked" if node.args else "full"

    @staticmethod
    def _is_hasher_update(node: ast.Call) -> bool:
        """True when node is hasher.update(...)."""
        if not isinstance(node.func, ast.Attribute):
            return False
        if node.func.attr != "update":
            return False
        return isinstance(node.func.value, ast.Name) and 'hasher' in node.func.value.id

    @staticmethod
    def _is_os_write(node: ast.Call) -> bool:
        """True when node is _os.write(fd, chunk)."""
        if not isinstance(node.func, ast.Attribute):
            return False
        if node.func.attr != "write":
            return False
        return isinstance(node.func.value, ast.Name) and node.func.value.id == "_os"

    @staticmethod
    def _is_chunks_append(node: ast.Call) -> bool:
        """True when node is chunks.append(...) or chunk_list.append(...)."""
        if not isinstance(node.func, ast.Attribute):
            return False
        if node.func.attr != "append":
            return False
        if isinstance(node.func.value, ast.Name):
            return 'chunk' in node.func.value.id.lower()
        return False

    # ── The core test ────────────────────────────────────

    def test_upload_function_uses_hasher_update_in_while(self):
        """upload_file 内 while 循环必须包含：分块读、hash 更新、流写，且无全量拼接"""
        source = self._get_upload_source()
        tree = ast.parse(source)

        # 1. 找到 upload_file 函数
        upload_fn = None
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "upload_file":
                upload_fn = node
                break
        assert upload_fn is not None, "未找到 upload_file 函数"

        # 2. 全局检查：upload_file 内不得有全量 file.read()（无参数）、chunks.append、bytes.join
        has_full_read = False
        has_chunks_append = False
        for node in ast.walk(upload_fn):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if self._is_read_call(node) == "full":
                    has_full_read = True
                if self._is_chunks_append(node):
                    has_chunks_append = True
        has_bytes_join = 'b"".join' in source or "b''.join" in source or "bytes.join" in source

        assert not has_full_read, (
            "upload_file 不应有 await file.read() 无 size 参数的全量内存读入"
        )
        assert not has_chunks_append, (
            "upload_file 不应有 chunks.append(...) 将分块收集到列表再全量拼接"
        )
        assert not has_bytes_join, (
            "upload_file 不应有 b''.join(chunks) 或类似的全量 bytes 拼接操作"
        )

        # 3. 逐一检查每个 while 循环体，确保：
        #    - await file.read(_CHUNK_SIZE) 在循环内
        #    - hasher.update(chunk) 在循环内
        #    - _os.write(tmp_fd, chunk) 在循环内
        while_nodes = [n for n in ast.walk(upload_fn) if isinstance(n, ast.While)]
        assert len(while_nodes) > 0, "upload_file 必须有至少一个 while 循环"

        valid_loops = 0
        for wi, while_node in enumerate(while_nodes):
            loop_has_chunked_read = False
            loop_has_hasher_update = False
            loop_has_os_write = False
            loop_has_full_read = False
            loop_has_chunks_append = False

            for inner in ast.walk(while_node):
                if isinstance(inner, ast.Call) and isinstance(inner.func, ast.Attribute):
                    kind = self._is_read_call(inner)
                    if kind == "chunked":
                        loop_has_chunked_read = True
                    elif kind == "full":
                        loop_has_full_read = True
                    if self._is_hasher_update(inner):
                        loop_has_hasher_update = True
                    if self._is_os_write(inner):
                        loop_has_os_write = True
                    if self._is_chunks_append(inner):
                        loop_has_chunks_append = True

            # 汇总
            failures = []
            if not loop_has_chunked_read:
                failures.append("缺少 await file.read(_CHUNK_SIZE) 分块读取")
            if not loop_has_hasher_update:
                failures.append("缺少 hasher.update(chunk) 滚动 hash")
            if not loop_has_os_write:
                failures.append("缺少 _os.write(tmp_fd, chunk) 流式写入")
            if loop_has_full_read:
                failures.append("while 循环内存在 file.read() 全量读入（无 size 参数）")
            if loop_has_chunks_append:
                failures.append("while 循环内存在 chunks.append(...) 全量收集")

            if failures:
                assert False, (
                    f"upload_file 第 {wi + 1} 个 while 循环不符合流式分块读写要求:\n"
                    + "\n".join(f"  - {f}" for f in failures)
                )
            valid_loops += 1

        assert valid_loops >= 1, "upload_file 中不存在符合流式分块读写规范的 while 循环"
