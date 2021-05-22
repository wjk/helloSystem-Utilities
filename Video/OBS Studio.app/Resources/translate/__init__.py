from collections     import OrderedDict, namedtuple
from collections.abc import Mapping
from io              import StringIO
from .plural         import c2py
import gettext, re


class PoFileTranslations(gettext.NullTranslations):
	_entries = dict()
	_plural_entries = dict()
	_info = dict()

	def info(self):
		return self._info

	def _parse(self, fp):
		parser = PoFileReader(PoFileEntry, fp)
		for entry in parser:
			self._entries[entry.id] = entry
			if entry.plural_id is not None:
				self._plural_entries[entry.plural_id] = entry

		meta_entry = self._entries['']
		if meta_entry is not None:
			del self._entries['']

			for line in meta_entry.string.split('\n'):
				parts = line.split(':')
				if len(parts) < 2:
					continue

				self._info[parts[0].strip()] = ' : '.join(x.strip() for x in parts[1:])

	def gettext(self, message):
		if message in self._entries:
			return self._entries[message].string
		else:
			return message

	def ngettext(self, singular, plural, n):
		if n == 1:
			entry = self._entries[singular]
		else:
			entry = self._plural_entries[plural]

		form_directive = self._info['Plural-Forms']
		processed_form_directive = re.sub(r'.*plural=([^;\r\n]+)(;.*|$)', r'\1', form_directive)
		if processed_form_directive == '' or processed_form_directive == form_directive:
			raise RuntimeError('Malformed Plural-Forms directive')

		compiled_rule = c2py(processed_form_directive)
		string_index = compiled_rule(n)
		return entry.plural_form(string_index)

	def pgettext(self, context, message) -> str:
		# TODO: Implement context support
		return self.gettext(message)

	def npgettext(self, context, msgid1, msgid2, n):
		# TODO: Implement context support
		return self.ngettext(msgid1, msgid2, n)


class PoFileParseError(IOError):
	pass


_Token = namedtuple('Token', ['type', 'value'])

_END = _Token('end', None)
_NIL = _Token('nil', None)


def _tokenize(lines):
	for line in lines:
		line = line.lstrip().rstrip('\n')

		# Empty lines
		if not line or line.isspace():
			yield _NIL
			continue

		# Comments
		if line[0] == '#':
			if len(line) == 1 or line[1].isspace():
				yield _Token('#', line[1:])
			elif len(line) == 2 or line[2].isspace():
				yield _Token(line[0:2], line[2:])
			else:
				raise PoFileParseError("Unknown comment marker")
			continue

		# Keywords and strings
		while line:
			if line[0] == '"':
				i = 1
				while i < len(line):
					if line[i] == '"': break
					i += 2 if line[i] == '\\' else 1
				if i >= len(line):
					raise PoFileParseError("Unterminated string")
				yield _Token('string', line[1:i])
				line = line[i+1:]
			elif line[0].isalpha():
				i = 0
				while i < len(line) and (line[i].isalpha() or line[i].isdigit() or line[i] in ['_','[',']']):
					i += 1
				yield _Token('keyword', line[:i])
				line = line[i:]
			else:
				raise PoFileParseError("Unknown character")
			line = line.lstrip()


class PoFileReader:
	__slots__ = ['Entry', 'file', '_header', '_peek', '_tokens']

	def __init__(self, entry, file):
		self.Entry   = entry
		self.file    = file
		self._tokens = _tokenize(file)

		self._peek = None; self._next() # prime the pump
		self._header = None # FIXME

	def _next(self):
		p, self._peek = self._peek, next(self._tokens, _END)
		return p

	def __iter__(self):
		return self

	def __next__(self):
		if self._peek.type == 'end':
			raise StopIteration

		entry = OrderedDict()

		# Comments
		while self._peek.type.startswith('#'):
			if self._peek.type in entry:
				raise PoFileParseError("Discontinuous comment")
			key   = self._peek.type
			lines = [self._next().value]
			while self._peek.type == key:
				lines.append(self._next().value)
			entry[key] = tuple(lines)

		# Keywords
		while self._peek.type == 'keyword':
			if self._peek.type in entry:
				raise PoFileParseError("Duplicate keyword")
			key   = self._next().value
			lines = []
			while self._peek.type == 'string':
				lines.append(self._next().value)
			if not lines:
				raise PoFileParseError("No strings after keyword")
			entry[key] = tuple(lines)

		# Empty
		if self._peek.type not in ['nil', 'end']:
			raise PoFileParseError("Expected end of entry")
		while self._peek.type == 'nil':
			self._next()

		return self.Entry(entry)


def _comment(key):
	def get(self): return self._getcomment(key)
	return property(get)


def _keyword(key):
	def get(self): return self._getkeyword(key)
	return property(get)


class PoFileEntry(Mapping):
	ESCAPES = {
		r'\"': '\"', r"\'": '\'', r'\\': '\\', r'\a': '\a', r'\b': '\b',
		r'\f': '\f', r'\n': '\n', r'\r': '\r', r'\t': '\t', r'\v': '\v',
	}

	@classmethod
	def unescape(cls, string):
		chunks = []; i = 0
		while True:
			j = string.find('\\', i)
			if j < 0: break
			chunks.append(string[i:j])
			raw = cls.ESCAPES.get(string[j:j+2], None)
			if raw is None:
				raise PoFileParseError("Unknown escape")
			chunks.append(raw)
			i = j + 2
		chunks.append(string[i:])
		return ''.join(chunks)

	DEFAULT = ['#', '#.', '#,', '#|', 'msgctxt', 'msgid', 'msgstr','msgid_plural']
	DEFAULT = OrderedDict((k, ()) for k in DEFAULT)

	def __init__(self, entries):
		is_indexed_msgstr = lambda x: re.match(r"msgstr\[\d+\]", x) is not None
		if not all(k in self.DEFAULT or is_indexed_msgstr(k) for k in entries):
			raise PoFileParseError("Unknown comment or keyword")
		self._dict = OrderedDict(entries)

	def __getitem__(self, key):
		return self._dict.get(key, self.DEFAULT[key])

	def __iter__(self):
		return iter(self._dict)

	def __len__(self):
		return len(self._dict)

	def __repr__(self):
		return '{}.PoFileEntry({!r})'.format(__name__, self._dict)

	def _getcomment(self, key):
		return '\n'.join(v[1:] for v in self[key])

	tcomment = _comment('#')
	pcomment = _comment('#.')

	LETTERS = set("abcdefghijklmnopqrstuvwxyz-")

	@property
	def flags(self):
		flags = set()
		for flag in self._getcomment('#,').split(','):
			flag = flag.strip()
			if not flag:
				continue
			if not all(c in self.LETTERS for c in flag):
				raise PoFileParseError("Unknown flag")
			if flag in flags:
				raise PoFileParseError("Duplicate flag")
			flags.add(flag)
		return flags

	@property
	def previous(self):
		# FIXME where to get PoFileReader?
		entries = list(PoFileReader(type(self), StringIO(self._getcomment('#|'))))
		if not entries:
			return None
		elif len(entries) == 1:
			return entries[0]
		else:
			raise PoFileParseError("Multiple previous entries")

	def _getkeyword(self, key):
		return self.unescape(''.join(self[key]))

	context = _keyword('msgctxt')
	id      = _keyword('msgid')
	string  = _keyword('msgstr')
	plural_id = _keyword('msgid_plural')

	def plural_form(self, n):
		return self._getkeyword('msgstr[' + str(n) + ']')
