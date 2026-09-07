class Plugin:
    def __init__(self, hooks):
        self.hooks = hooks

    def activate(self, context):
        return [hook(context) for hook in self.hooks]
