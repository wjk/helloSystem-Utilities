# -*- coding: utf-8 -*-
"""
Subset of Python's standard gettext.py, containing
only the functions required to parse a Plural-Forms
expression.
"""

import re

# Expression parsing for plural form selection.
#
# The gettext library supports a small subset of C syntax.  The only
# incompatible difference is that integer literals starting with zero are
# decimal.
#
# https://www.gnu.org/software/gettext/manual/gettext.html#Plural-forms
# http://git.savannah.gnu.org/cgit/gettext.git/tree/gettext-runtime/intl/plural.y

_token_pattern = re.compile(r"""
        (?P<WHITESPACES>[ \t]+)                    | # spaces and horizontal tabs
        (?P<NUMBER>[0-9]+\b)                       | # decimal integer
        (?P<NAME>n\b)                              | # only n is allowed
        (?P<PARENTHESIS>[()])                      |
        (?P<OPERATOR>[-*/%+?:]|[><!]=?|==|&&|\|\|) | # !, *, /, %, +, -, <, >,
                                                     # <=, >=, ==, !=, &&, ||,
                                                     # ? :
                                                     # unary and bitwise ops
                                                     # not allowed
        (?P<INVALID>\w+|.)                           # invalid token
    """, re.VERBOSE|re.DOTALL)

def _tokenize(plural):
    for mo in re.finditer(_token_pattern, plural):
        kind = mo.lastgroup
        if kind == 'WHITESPACES':
            continue
        value = mo.group(kind)
        if kind == 'INVALID':
            raise ValueError('invalid token in plural form: %s' % value)
        yield value
    yield ''

def _error(value):
    if value:
        return ValueError('unexpected token in plural form: %s' % value)
    else:
        return ValueError('unexpected end of plural form')

_binary_ops = (
    ('||',),
    ('&&',),
    ('==', '!='),
    ('<', '>', '<=', '>='),
    ('+', '-'),
    ('*', '/', '%'),
)
_binary_ops = {op: i for i, ops in enumerate(_binary_ops, 1) for op in ops}
_c2py_ops = {'||': 'or', '&&': 'and', '/': '//'}

def _parse(tokens, priority=-1):
    result = ''
    nexttok = next(tokens)
    while nexttok == '!':
        result += 'not '
        nexttok = next(tokens)

    if nexttok == '(':
        sub, nexttok = _parse(tokens)
        result = '%s(%s)' % (result, sub)
        if nexttok != ')':
            raise ValueError('unbalanced parenthesis in plural form')
    elif nexttok == 'n':
        result = '%s%s' % (result, nexttok)
    else:
        try:
            value = int(nexttok, 10)
        except ValueError:
            raise _error(nexttok) from None
        result = '%s%d' % (result, value)
    nexttok = next(tokens)

    j = 100
    while nexttok in _binary_ops:
        i = _binary_ops[nexttok]
        if i < priority:
            break
        # Break chained comparisons
        if i in (3, 4) and j in (3, 4):  # '==', '!=', '<', '>', '<=', '>='
            result = '(%s)' % result
        # Replace some C operators by their Python equivalents
        op = _c2py_ops.get(nexttok, nexttok)
        right, nexttok = _parse(tokens, i + 1)
        result = '%s %s %s' % (result, op, right)
        j = i
    if j == priority == 4:  # '<', '>', '<=', '>='
        result = '(%s)' % result

    if nexttok == '?' and priority <= 0:
        if_true, nexttok = _parse(tokens, 0)
        if nexttok != ':':
            raise _error(nexttok)
        if_false, nexttok = _parse(tokens)
        result = '%s if %s else %s' % (if_true, result, if_false)
        if priority == 0:
            result = '(%s)' % result

    return result, nexttok

def _as_int(n):
    try:
        i = round(n)
    except TypeError:
        raise TypeError('Plural value must be an integer, got %s' %
                        (n.__class__.__name__,)) from None
    import warnings
    warnings.warn('Plural value must be an integer, got %s' %
                  (n.__class__.__name__,),
                  DeprecationWarning, 4)
    return n

def c2py(plural):
    """Gets a C expression as used in PO files for plural forms and returns a
    Python function that implements an equivalent expression.
    """

    if len(plural) > 1000:
        raise ValueError('plural form expression is too long')
    try:
        result, nexttok = _parse(_tokenize(plural))
        if nexttok:
            raise _error(nexttok)

        depth = 0
        for c in result:
            if c == '(':
                depth += 1
                if depth > 20:
                    # Python compiler limit is about 90.
                    # The most complex example has 2.
                    raise ValueError('plural form expression is too complex')
            elif c == ')':
                depth -= 1

        ns = {'_as_int': _as_int}
        exec('''if True:
            def func(n):
                if not isinstance(n, int):
                    n = _as_int(n)
                return int(%s)
            ''' % result, ns)
        return ns['func']
    except RecursionError:
        # Recursion error can be raised in _parse() or exec().
        raise ValueError('plural form expression is too complex')
