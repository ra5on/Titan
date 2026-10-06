"""Root agent integration for external backups and local health notifications."""
from .backups import Backups
from .monitoring import Monitor


class ServicesMixin:
    def initialize_services(self, runner):
        self._backups = Backups(self, runner)
        self._monitor = Monitor(self, runner)

    @property
    def backups(self):
        if not hasattr(self, "_backups"):
            from .host import run
            self._backups = Backups(self, run)
        return self._backups

    @property
    def monitor(self):
        if not hasattr(self, "_monitor"):
            from .host import run
            self._monitor = Monitor(self, run)
        return self._monitor

    def service_status(self):
        return self.monitor.service_status()

    def op_backup_settings(self):
        return self.backups.settings()

    def op_backup_save_settings(self, **value):
        return self.backups.save_settings(value)

    def op_backups(self):
        return {"items": self.backups.list(), "last": self.backups.state().get("last"),
                "config_restore": self.load("config-restore-result", {})}

    def op_backup_create(self, shares=None, include_config=None):
        return self.backups.create(shares, include_config)

    def op_backup_verify(self, backup):
        return self.backups.verify(backup)

    def op_backup_restore(self, backup, share, name):
        return self.backups.restore(backup, share, name)

    def op_backup_config_export(self, backup):
        return self.backups.export_config(backup)

    def op_backup_config_restore(self, backup, confirmation):
        return self.backups.restore_config(backup, confirmation)

    def op_backup_scheduled(self):
        return self.backups.scheduled()

    def op_monitoring(self):
        return self.monitor.check()

    def op_monitoring_check(self, force=False):
        return self.monitor.check(force)

    def op_monitoring_ack(self, id):
        return self.monitor.acknowledge(id)
