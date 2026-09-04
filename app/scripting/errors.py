# Hera - Hercules Hyperion GUI - by Mockba the Borg
#
"""Error type for the scripting API — carries an HTTP status code."""


class ApiError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message
