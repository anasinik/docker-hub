
class MockRegistryClient:
    def is_available(self):
        return True

    def list_tags(self, repository):
        return [
            {
                "name": "latest",
                "digest": "sha256:4e58d7d5dfe1443507f0c3099a04ac3f13c500a7b3caea02ee44fd6d0786bdf8",
                "pushed_at": None,
            },
            {
                "name": "1.0.0",
                "digest": "sha256:ae0a456b0a5b5a05196cf4e6392e597b5a4e99545c6a5254f5ddca6ae6d016a1",
                "pushed_at": None,
            },
        ]