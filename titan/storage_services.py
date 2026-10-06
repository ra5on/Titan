"""Host mixin for maintenance, backup browsing and notification preferences."""
from .storage_maintenance import StorageMaintenance
from .notification_delivery import NotificationDelivery


class StorageServicesMixin:
    @property
    def maintenance(self):
        if not hasattr(self, "_maintenance"):
            from .host import run
            self._maintenance = StorageMaintenance(self, run)
        return self._maintenance

    @property
    def notification_delivery(self):
        if not hasattr(self, "_notification_delivery"):
            self._notification_delivery = NotificationDelivery(self)
        return self._notification_delivery

    def op_storage_maintenance(self):
        return self.maintenance.status()

    def op_storage_maintenance_save(self, **job):
        return self.maintenance.save_job(**job)

    def op_storage_maintenance_remove(self, id):
        return self.maintenance.remove_job(id)

    def op_storage_maintenance_scheduled(self):
        return self.maintenance.scheduled()

    def op_smart_test(self, disk, test="short"):
        return self.maintenance.smart_test(disk, test)

    def op_snapshot_restore(self, snapshot, name):
        return self.maintenance.restore_snapshot(snapshot, name)

    def op_snapshot_remove(self, snapshot, confirmed=False):
        return self.maintenance.remove_snapshot(snapshot, confirmed)

    def op_backup_browse(self, backup, path="", offset=0, limit=200):
        return self.backups.browse(backup, path, offset, limit)

    def op_backup_restore_selection(self, backup, paths, share, name):
        return self.backups.restore_selection(backup, paths, share, name)

    def op_notification_settings(self):
        return self.notification_delivery.settings()

    def op_notification_save_settings(self, **settings):
        return self.notification_delivery.save_settings(**settings)

    def op_notification_test(self):
        return self.notification_delivery.test()
