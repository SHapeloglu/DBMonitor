"""
adapters paketi: her veritabanı türü için bir adapter dosyası içerir (mssql, oracle, mysql, postgresql, generic_odbc).
Her adapter core/base_adapter.DBAdapter sınıfını miras alır ve core/adapter_registry tarafından isimle yüklenir.
Yeni bir DB türü eklemek için bu klasöre yeni bir modül koyup config/databases.yaml içinde adapter yolunu vermek yeterlidir.
"""
