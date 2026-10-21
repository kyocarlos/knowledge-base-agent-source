class IntegrationError(Exception):
    def __init__(self, code, message, retryable=False):
        self.code, self.message, self.retryable = code, message, retryable
        super().__init__(code)
class LeaseLost(IntegrationError):
    def __init__(self): super().__init__("LEASE_LOST", "Worker lease no longer owned")
