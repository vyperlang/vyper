class Inf:
    """Singleton representing unbounded length."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self):
        return "INF"


INF = Inf()
