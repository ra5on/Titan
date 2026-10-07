"""PTY sessions remain scoped to one authenticated web session."""
from .terminal import TerminalManager


class TerminalMixin:
    @property
    def terminals(self):
        with self.terminal_lock:
            if not hasattr(self, '_terminals'):
                self._terminals = TerminalManager(cwd=str(self.share_root), user="titan-files")
            return self._terminals

    def op_terminal_create(self, owner, cols=100, rows=30):
        return self.terminals.create(owner, cols, rows)

    def op_terminal_poll(self, owner, id, timeout=0):
        return self.terminals.poll(owner, id, timeout)

    def op_terminal_write(self, owner, id, data):
        return self.terminals.write(owner, id, data)

    def op_terminal_resize(self, owner, id, cols, rows):
        return self.terminals.resize(owner, id, cols, rows)

    def op_terminal_close(self, owner, id):
        return self.terminals.close(owner, id)

    @property
    def root_terminals(self):
        with self.terminal_lock:
            if not hasattr(self, '_root_terminals'):
                self._root_terminals = TerminalManager(cwd='/', user='root', allow_root=True,
                    max_ttl=30 * 60, sweep_interval=1)
            return self._root_terminals

    def op_root_terminal_create(self, owner, deadline, cols=100, rows=30):
        return self.root_terminals.create(owner, cols, rows, deadline=deadline)

    def op_root_terminal_poll(self, owner, id, timeout=0):
        return self.root_terminals.poll(owner, id, timeout)

    def op_root_terminal_write(self, owner, id, data):
        return self.root_terminals.write(owner, id, data)

    def op_root_terminal_resize(self, owner, id, cols, rows):
        return self.root_terminals.resize(owner, id, cols, rows)

    def op_root_terminal_close(self, owner, id):
        return self.root_terminals.close(owner, id)

    def shutdown_root_terminals(self):
        if hasattr(self, '_root_terminals'):
            self._root_terminals.close_all()
