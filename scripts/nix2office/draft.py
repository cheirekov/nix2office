"""Private, atomic checkpoints of non-secret menu answers; never store passwords."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
from .config import ConfigError


def directory(parent):
    p = Path(parent) / '.nix2office'
    if p.is_symlink():
        raise ConfigError('Draft directory must not be a symlink')
    p.mkdir(mode=0o700, parents=True, exist_ok=True)
    if p.stat().st_uid != os.getuid():
        raise ConfigError('Draft directory has a different owner')
    p.chmod(0o700)
    (p / '.gitignore').write_text('*\n')
    return p


def save(path, value):
    fd, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, ensure_ascii=False)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def load(path):
    if path.is_symlink():
        raise ConfigError('Draft must not be a symlink')
    if not path.exists():
        return {}
    if path.stat().st_uid != os.getuid():
        raise ConfigError('Draft has a different owner')
    try:
        value = json.loads(path.read_text())
        return value if isinstance(value, dict) else {}
    except (ValueError, OSError):
        return {}


class Menus:
    def __init__(self, q, dest, scope=''):
        self.q = q
        token = hashlib.sha256((str(dest) + '\n' + scope).encode()).hexdigest()[:20]
        self.path = directory(Path(dest).parent) / (token + '.json')
        self.answers = {}
        previous = load(self.path)
        if isinstance(previous.get('answers'), dict) and previous['answers']:
            resume = q.confirm('Намерена е локална чернова за тази цел. Да използвам отговорите като начални стойности?', default=True).ask()
            if resume is None:
                raise KeyboardInterrupt
            if resume:
                self.answers = previous['answers']

    def forget(self, message):
        self.answers.pop(message, None)
        save(self.path, {'answers': self.answers})

    def __getattr__(self, name):
        target = getattr(self.q, name)
        if name not in ('text', 'confirm', 'select', 'checkbox'):
            return target
        def prompt(message, *args, **kwargs):
            old = self.answers.get(message)
            choices = kwargs.get('choices', [])
            def value(c):
                return c if isinstance(c, str) else c.value
            if name == 'checkbox' and isinstance(old, list):
                kwargs['choices'] = [self.q.Choice(c.title if not isinstance(c, str) else c, value=value(c), checked=value(c) in old) for c in choices]
            elif name == 'select' and old in [value(c) for c in choices]:
                kwargs['default'] = old
            elif name == 'text' and isinstance(old, str):
                kwargs['default'] = old
            elif name == 'confirm' and type(old) is bool:
                kwargs['default'] = old
            question = target(message, *args, **kwargs)
            parent = self
            class Answer:
                def ask(self):
                    answer = question.ask()
                    if answer is not None:
                        parent.answers[message] = answer
                        save(parent.path, {'answers': parent.answers})
                    return answer
            return Answer()
        return prompt
