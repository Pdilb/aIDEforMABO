"""
Mabo IDE v2.0 - 全面翻新版
集成 Mabo 语言 V2.0 解释器 | 修复行号/补全/运行阻塞 | 快捷键 | 深色浅色主题
"""
import sys
import os
import re
import io
import math
import random
import json
from pathlib import Path

from PyQt6.QtCore import Qt, QThread, pyqtSignal, QRect, QSize, QTimer, QStringListModel, QProcess
from PyQt6.QtGui import (
    QFont, QColor, QTextCharFormat, QSyntaxHighlighter,
    QKeySequence, QAction, QPainter, QTextCursor
)
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QTabWidget, QPlainTextEdit, QListWidget, QToolBar,
    QFileDialog, QMessageBox, QDialog, QCheckBox, QSpinBox,
    QLabel, QDialogButtonBox, QCompleter, QStatusBar, QMenu,
    QInputDialog, QLineEdit
)

# ============================================================================
#                          MABO 语言 V2.0 解释器
# ============================================================================

# ========== 自动导入管理 ==========
_imported_modules = set()

def auto_import(module_name):
    global _imported_modules
    if module_name in _imported_modules:
        return True
    try:
        if module_name == 'math':
            globals()['math'] = __import__('math')
        elif module_name == 'random':
            globals()['random'] = __import__('random')
        elif module_name == 'datetime':
            globals()['datetime'] = __import__('datetime')
        _imported_modules.add(module_name)
        return True
    except ImportError:
        return False

# ========== 智能纠错建议 ==========
COMMAND_SUGGESTIONS = {
    'iff': 'if', 'els': 'else', 'elifff': 'elif', 'whle': 'while',
    'whil': 'while', 'fo': 'for', 'retrn': 'return', 'retun': 'return',
    'deff': 'def', 'defi': 'def', 'braek': 'break', 'contiue': 'continue',
    'ou': 'out', 'outt': 'out', 'inn': 'in', 'lenn': 'len',
    'typpe': 'type', 'strr': 'str', 'floatt': 'float', 'rangge': 'range',
    'randdom': 'random', 'choise': 'choice', 'shufffle': 'shuffle',
}

def suggest_word(word):
    if not word or len(word) < 2:
        return None
    word_lower = word.lower()
    if word_lower in COMMAND_SUGGESTIONS:
        return COMMAND_SUGGESTIONS[word_lower]
    for wrong, correct in COMMAND_SUGGESTIONS.items():
        if word_lower in wrong or wrong in word_lower:
            return correct
    return None

# ========== 词法分析器 ==========
class Token:
    def __init__(self, type, value, line, col=0):
        self.type = type
        self.value = value
        self.line = line
        self.col = col
    def __repr__(self):
        return f"Token({self.type}, {repr(self.value)})"

class Lexer:
    def __init__(self, source):
        self.source = source
        self.tokens = []
        self.current_pos = 0
        self.line = 1
        self.col = 1

    def tokenize(self):
        while self.current_pos < len(self.source):
            ch = self.source[self.current_pos]

            if ch in ' \t':
                self.current_pos += 1
                self.col += 1
                continue
            elif ch == '\n':
                self.line += 1
                self.col = 1
                self.current_pos += 1
                continue

            # 注释
            if ch == '#':
                while self.current_pos < len(self.source) and self.source[self.current_pos] != '\n':
                    self.current_pos += 1
                continue

            # 字符串
            if ch == '"' or ch == "'":
                start_col = self.col
                start = self.current_pos
                quote_char = ch
                self.current_pos += 1
                self.col += 1
                while self.current_pos < len(self.source) and self.source[self.current_pos] != quote_char:
                    if self.source[self.current_pos] == '\\':
                        self.current_pos += 2
                        self.col += 2
                    else:
                        self.current_pos += 1
                        self.col += 1
                self.current_pos += 1
                self.col += 1
                str_value = self.source[start+1:self.current_pos-1]
                self.tokens.append(Token('STRING', str_value, self.line, start_col))
                continue

            # 数字
            if ch.isdigit():
                start_col = self.col
                start = self.current_pos
                while self.current_pos < len(self.source) and (self.source[self.current_pos].isdigit() or self.source[self.current_pos] == '.'):
                    self.current_pos += 1
                    self.col += 1
                num_str = self.source[start:self.current_pos]
                if '.' in num_str:
                    self.tokens.append(Token('FLOAT', float(num_str), self.line, start_col))
                else:
                    self.tokens.append(Token('INT', int(num_str), self.line, start_col))
                continue

            # 标识符 / 关键字
            if ch.isalpha() or ch == '_':
                start_col = self.col
                start = self.current_pos
                while self.current_pos < len(self.source) and (self.source[self.current_pos].isalpha() or self.source[self.current_pos].isdigit() or self.source[self.current_pos] == '_'):
                    self.current_pos += 1
                    self.col += 1
                ident = self.source[start:self.current_pos]
                keywords = ['if', 'else', 'elif', 'while', 'def', 'return',
                           'True', 'False', 'None', 'and', 'or', 'not', 'for',
                           'break', 'continue', 'in']
                if ident in keywords:
                    if ident in ['True', 'False']:
                        self.tokens.append(Token('BOOLEAN', ident == 'True', self.line, start_col))
                    elif ident == 'None':
                        self.tokens.append(Token('NONE', None, self.line, start_col))
                    else:
                        self.tokens.append(Token('KEYWORD', ident, self.line, start_col))
                else:
                    self.tokens.append(Token('IDENTIFIER', ident, self.line, start_col))
                continue

            # 运算符 (注意: {} 由下面的 LBRACE/RBRACE 处理, 不在这里)
            if ch in '+-*/=<>!%;,':
                start_col = self.col
                # 复合赋值
                if ch in '+-*/' and self.current_pos + 1 < len(self.source) and self.source[self.current_pos + 1] == '=':
                    op = ch + '='
                    self.current_pos += 2
                    self.col += 2
                    self.tokens.append(Token('OPERATOR', op, self.line, start_col))
                # 自增自减
                elif ch in '+-' and self.current_pos + 1 < len(self.source) and self.source[self.current_pos + 1] == ch:
                    op = ch + ch
                    self.current_pos += 2
                    self.col += 2
                    self.tokens.append(Token('OPERATOR', op, self.line, start_col))
                elif ch in '<>' and self.current_pos + 1 < len(self.source) and self.source[self.current_pos + 1] == '=':
                    op = ch + '='
                    self.current_pos += 2
                    self.col += 2
                    self.tokens.append(Token('OPERATOR', op, self.line, start_col))
                elif ch == '=' and self.current_pos + 1 < len(self.source) and self.source[self.current_pos + 1] == '=':
                    self.current_pos += 2
                    self.col += 2
                    self.tokens.append(Token('OPERATOR', '==', self.line, start_col))
                elif ch == '!' and self.current_pos + 1 < len(self.source) and self.source[self.current_pos + 1] == '=':
                    self.current_pos += 2
                    self.col += 2
                    self.tokens.append(Token('OPERATOR', '!=', self.line, start_col))
                else:
                    self.current_pos += 1
                    self.col += 1
                    self.tokens.append(Token('OPERATOR', ch, self.line, start_col))
                continue

            if ch == ':':
                self.current_pos += 1
                self.col += 1
                self.tokens.append(Token('COLON', ':', self.line, self.col - 1))
                continue
            if ch == '(':
                self.current_pos += 1
                self.col += 1
                self.tokens.append(Token('LPAREN', '(', self.line, self.col - 1))
                continue
            if ch == ')':
                self.current_pos += 1
                self.col += 1
                self.tokens.append(Token('RPAREN', ')', self.line, self.col - 1))
                continue
            if ch == '{' or ch == '\uff5b':
                self.current_pos += 1
                self.col += 1
                self.tokens.append(Token('LBRACE', '{', self.line, self.col - 1))
                continue
            if ch == '}' or ch == '\uff5d':
                self.current_pos += 1
                self.col += 1
                self.tokens.append(Token('RBRACE', '}', self.line, self.col - 1))
                continue
            if ch == '[':
                self.current_pos += 1
                self.col += 1
                self.tokens.append(Token('LBRACKET', '[', self.line, self.col - 1))
                continue
            if ch == ']':
                self.current_pos += 1
                self.col += 1
                self.tokens.append(Token('RBRACKET', ']', self.line, self.col - 1))
                continue
            if ch == '.':
                self.current_pos += 1
                self.col += 1
                self.tokens.append(Token('DOT', '.', self.line, self.col - 1))
                continue

            raise SyntaxError(f"\u7b2c {self.line} \u884c \u7b2c {self.col} \u5217: \u975e\u6cd5\u5b57\u7b26 '{ch}'")

        return self.tokens

# ========== 增强错误类 ==========
class MabaSyntaxError(SyntaxError):
    def __init__(self, line, col, message, token_value=None):
        self.line = line
        self.col = col
        self.message = message
        self.token_value = token_value
        super().__init__(f"\u7b2c {line} \u884c: {message}")

    def format_error(self, source_lines, offset_line=0):
        actual_line = self.line - offset_line
        if not source_lines or actual_line < 1 or actual_line > len(source_lines):
            return str(self)
        error_line = source_lines[actual_line - 1].rstrip()
        pointer = ' ' * (self.col - 1) + '^' if self.col else '^'
        suggestion = suggest_word(self.token_value) if self.token_value else None
        result = f"\n  \u7b2c {actual_line} \u884c:\n    {error_line}\n    {pointer}\n  \u9519\u8bef: {self.message}"
        if suggestion:
            result += f"\n\n  \u60a8\u662f\u4e0d\u662f\u60f3\u5199 '{suggestion}'\uff1f"
        return result

# ========== AST 节点 ==========
class AST: pass
class Program(AST):
    def __init__(self, stmts): self.statements = stmts
class Declaration(AST):
    def __init__(self, vt, vn, val, ln, co): self.var_type=vt; self.var_name=vn; self.value=val; self.line=ln; self.col=co
class Assignment(AST):
    def __init__(self, vn, val, ln, co): self.var_name=vn; self.value=val; self.line=ln; self.col=co
class CompoundAssign(AST):
    def __init__(self, vn, op, val, ln, co): self.var_name=vn; self.operator=op; self.value=val; self.line=ln; self.col=co
class IncDec(AST):
    def __init__(self, vn, op, ln, co): self.var_name=vn; self.operator=op; self.line=ln; self.col=co
class BinaryOp(AST):
    def __init__(self, l, op, r, ln, co): self.left=l; self.operator=op; self.right=r; self.line=ln; self.col=co
class UnaryOp(AST):
    def __init__(self, op, od, ln, co): self.operator=op; self.operand=od; self.line=ln; self.col=co
class IfStatement(AST):
    def __init__(self, cond, tb, eb, fb, ln, co): self.condition=cond; self.true_branch=tb; self.elif_branches=eb; self.false_branch=fb; self.line=ln; self.col=co
class WhileStatement(AST):
    def __init__(self, cond, body, ln, co): self.condition=cond; self.body=body; self.line=ln; self.col=co
class ForStatement(AST):
    def __init__(self, it, iter_obj, body, ln, co): self.iterator=it; self.iterable=iter_obj; self.body=body; self.line=ln; self.col=co
class FunctionDef(AST):
    def __init__(self, nm, ps, ds, body, ln, co): self.name=nm; self.params=ps; self.defaults=ds; self.body=body; self.line=ln; self.col=co
class FunctionCall(AST):
    def __init__(self, nm, args, kw, ln, co): self.name=nm; self.args=args; self.kwargs=kw; self.line=ln; self.col=co
class ReturnStatement(AST):
    def __init__(self, val, ln, co): self.value=val; self.line=ln; self.col=co
class OutStatement(AST):
    def __init__(self, vals, ln, co): self.values=vals; self.line=ln; self.col=co
class InFunction(AST):
    def __init__(self, prompt, ln, co): self.prompt=prompt; self.line=ln; self.col=co
class VarReference(AST):
    def __init__(self, nm, ln, co): self.name=nm; self.line=ln; self.col=co
class ListLiteral(AST):
    def __init__(self, elems, ln, co): self.elements=elems; self.line=ln; self.col=co
class ListIndex(AST):
    def __init__(self, le, idx, ln, co): self.list_expr=le; self.indices=idx; self.line=ln; self.col=co
class DictionaryLiteral(AST):
    def __init__(self, pairs, ln, co): self.pairs=pairs; self.line=ln; self.col=co
class StringMethod(AST):
    def __init__(self, obj, mtd, args, ln, co): self.obj=obj; self.method=mtd; self.args=args; self.line=ln; self.col=co
class BreakStatement(AST):
    def __init__(self, ln, co): self.line=ln; self.col=co
class ContinueStatement(AST):
    def __init__(self, ln, co): self.line=ln; self.col=co

# ========== 语法分析器 ==========
class Parser:
    def __init__(self, tokens, source_lines=None, offset_line=0):
        self.tokens = tokens
        self.pos = 0
        self.source_lines = source_lines
        self.offset_line = offset_line

    def current_token(self):
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def consume(self, expected_type=None, expected_value=None):
        token = self.current_token()
        if not token:
            raise MabaSyntaxError(self.tokens[-1].line if self.tokens else 1, 1, "\u610f\u5916\u7684\u6587\u4ef6\u7ed3\u675f")
        if expected_type and token.type != expected_type:
            msg = f"\u671f\u671b {expected_type}\uff0c\u5f97\u5230 {token.type}"
            if expected_type == 'IDENTIFIER':
                msg = f"\u671f\u671b\u6807\u8bc6\u7b26\uff0c\u5f97\u5230 '{token.value}'"
            err = MabaSyntaxError(token.line, token.col, msg, token.value)
            raise err
        if expected_value and token.value != expected_value:
            err = MabaSyntaxError(token.line, token.col, f"\u671f\u671b '{expected_value}'\uff0c\u5f97\u5230 '{token.value}'", token.value)
            raise err
        self.pos += 1
        return token

    def peek(self):
        return self.tokens[self.pos + 1] if self.pos + 1 < len(self.tokens) else None

    def consume_optional_semicolon(self):
        t = self.current_token()
        if t and t.type == 'OPERATOR' and t.value == ';':
            self.consume()

    def parse(self):
        stmts = []
        while self.current_token():
            s = self.parse_statement()
            if s: stmts.append(s)
        return Program(stmts)

    def parse_statement(self):
        token = self.current_token()
        if not token: return None

        if token.type == 'KEYWORD' and token.value == 'break':
            self.consume()
            self.consume_optional_semicolon()
            return BreakStatement(token.line, token.col)
        if token.type == 'KEYWORD' and token.value == 'continue':
            self.consume()
            self.consume_optional_semicolon()
            return ContinueStatement(token.line, token.col)
        if token.type == 'KEYWORD' and token.value == 'def':
            return self.parse_function_def()
        if token.type == 'KEYWORD' and token.value == 'return':
            self.consume()
            val = None
            if self.current_token() and not (self.current_token().type == 'OPERATOR' and self.current_token().value == ';'):
                val = self.parse_expression()
            self.consume_optional_semicolon()
            return ReturnStatement(val, token.line, token.col)
        if token.type == 'KEYWORD' and token.value == 'if':
            return self.parse_if()
        if token.type == 'KEYWORD' and token.value == 'while':
            return self.parse_while()
        if token.type == 'KEYWORD' and token.value == 'for':
            return self.parse_for()

        # 类型声明
        if token.type == 'IDENTIFIER' and token.value in ['zheng', 'xiao', 'fu', 'list', 'dict']:
            var_type = token.value
            self.consume()
            self.consume('COLON')
            var_name = self.consume('IDENTIFIER').value
            if self.current_token() and self.current_token().type == 'OPERATOR' and self.current_token().value == '=':
                self.consume()
                value = self.parse_expression()
            else:
                value = {'zheng':0, 'xiao':0.0, 'fu':'', 'list':[], 'dict':{}}[var_type]
            self.consume_optional_semicolon()
            return Declaration(var_type, var_name, value, token.line, token.col)

        # out 输出
        if token.type == 'IDENTIFIER' and token.value == 'out':
            self.consume()
            if self.current_token() and self.current_token().type == 'OPERATOR' and self.current_token().value == '=':
                self.consume()
                val = self.parse_expression()
                self.consume_optional_semicolon()
                return Assignment('out', val, token.line, token.col)
            if self.current_token() and self.current_token().type == 'STRING':
                sv = self.consume().value
                self.consume_optional_semicolon()
                return OutStatement([sv], token.line, token.col)
            elif self.current_token() and self.current_token().type == 'LPAREN':
                self.consume()
                vals = []
                while self.current_token() and self.current_token().type != 'RPAREN':
                    vals.append(self.parse_expression())
                    if self.current_token() and self.current_token().type == 'OPERATOR' and self.current_token().value == ',':
                        self.consume()
                self.consume('RPAREN')
                self.consume_optional_semicolon()
                return OutStatement(vals, token.line, token.col)
            else:
                expr = self.parse_expression()
                self.consume_optional_semicolon()
                return OutStatement([expr], token.line, token.col)

        # 赋值 / 复合赋值 / 自增自减
        if token.type == 'IDENTIFIER':
            var_name = token.value
            self.consume()
            if self.current_token() and self.current_token().type == 'OPERATOR' and self.current_token().value in ['++', '--']:
                op = self.consume().value
                self.consume_optional_semicolon()
                return IncDec(var_name, op, token.line, token.col)
            if self.current_token() and self.current_token().type == 'OPERATOR' and self.current_token().value in ['+=', '-=', '*=', '/=']:
                op = self.consume().value
                val = self.parse_expression()
                self.consume_optional_semicolon()
                return CompoundAssign(var_name, op, val, token.line, token.col)
            if self.current_token() and self.current_token().type == 'OPERATOR' and self.current_token().value == '=':
                self.consume()
                val = self.parse_expression()
                self.consume_optional_semicolon()
                return Assignment(var_name, val, token.line, token.col)

        # 函数调用
        if token.type == 'IDENTIFIER' and self.peek() and self.peek().type == 'LPAREN':
            return self.parse_function_call()

        expr = self.parse_expression()
        self.consume_optional_semicolon()
        return expr

    def parse_block(self):
        self.consume('LBRACE')
        body = []
        while self.current_token() and self.current_token().type != 'RBRACE':
            s = self.parse_statement()
            if s: body.append(s)
        self.consume('RBRACE')
        return body

    def parse_if(self):
        t = self.current_token()
        self.consume('KEYWORD', 'if')
        cond = self.parse_expression()
        tb = self.parse_block() if self.current_token() and self.current_token().type == 'LBRACE' else [self.parse_statement()]
        elif_branches = []
        while self.current_token() and self.current_token().type == 'KEYWORD' and self.current_token().value == 'elif':
            self.consume()
            ec = self.parse_expression()
            eb = self.parse_block() if self.current_token() and self.current_token().type == 'LBRACE' else [self.parse_statement()]
            elif_branches.append((ec, eb))
        fb = None
        if self.current_token() and self.current_token().type == 'KEYWORD' and self.current_token().value == 'else':
            self.consume()
            fb = self.parse_block() if self.current_token() and self.current_token().type == 'LBRACE' else [self.parse_statement()]
        return IfStatement(cond, tb, elif_branches, fb, t.line, t.col)

    def parse_while(self):
        t = self.current_token()
        self.consume('KEYWORD', 'while')
        cond = self.parse_expression()
        body = self.parse_block() if self.current_token() and self.current_token().type == 'LBRACE' else [self.parse_statement()]
        return WhileStatement(cond, body, t.line, t.col)

    def parse_for(self):
        t = self.current_token()
        self.consume('KEYWORD', 'for')
        it = self.consume('IDENTIFIER').value
        self.consume('KEYWORD', 'in')
        iter_obj = self.parse_expression()
        body = self.parse_block() if self.current_token() and self.current_token().type == 'LBRACE' else [self.parse_statement()]
        return ForStatement(it, iter_obj, body, t.line, t.col)

    def parse_function_def(self):
        t = self.current_token()
        self.consume('KEYWORD', 'def')
        name = self.consume('IDENTIFIER').value
        self.consume('LPAREN')
        params, defaults, has_d = [], [], False
        if self.current_token() and self.current_token().type != 'RPAREN':
            while True:
                params.append(self.consume('IDENTIFIER').value)
                if self.current_token() and self.current_token().type == 'OPERATOR' and self.current_token().value == '=':
                    has_d = True
                    self.consume()
                    defaults.append(self.parse_expression())
                else:
                    if has_d:
                        raise MabaSyntaxError(t.line, t.col, "\u5e26\u9ed8\u8ba4\u503c\u7684\u53c2\u6570\u540e\u9762\u4e0d\u80fd\u8ddf\u6ca1\u6709\u9ed8\u8ba4\u503c\u7684\u53c2\u6570")
                    defaults.append(None)
                if self.current_token() and self.current_token().type == 'OPERATOR' and self.current_token().value == ',':
                    self.consume()
                    continue
                break
        self.consume('RPAREN')
        body = self.parse_block()
        return FunctionDef(name, params, defaults, body, t.line, t.col)

    def parse_function_call(self):
        t = self.current_token()
        name = self.consume('IDENTIFIER').value
        self.consume('LPAREN')
        args, kwargs = [], []
        if self.current_token() and self.current_token().type != 'RPAREN':
            while True:
                if (self.current_token().type == 'IDENTIFIER' and
                    self.peek() and self.peek().type == 'OPERATOR' and self.peek().value == '='):
                    kn = self.consume('IDENTIFIER').value
                    self.consume('OPERATOR', '=')
                    kwargs.append((kn, self.parse_expression()))
                else:
                    args.append(self.parse_expression())
                if self.current_token() and self.current_token().type == 'OPERATOR' and self.current_token().value == ',':
                    self.consume()
                    continue
                break
        self.consume('RPAREN')
        self.consume_optional_semicolon()
        return FunctionCall(name, args, kwargs, t.line, t.col)

    def parse_expression(self, min_prec=0):
        return self.parse_binary_op(min_prec)

    def parse_binary_op(self, min_prec):
        left = self.parse_unary()
        while True:
            t = self.current_token()
            if not t or t.type != 'OPERATOR': break
            prec = -1 if t.value in ['and','or'] else self.get_precedence(t.value)
            if prec < min_prec: break
            self.consume()
            right = self.parse_binary_op(prec + 1)
            left = BinaryOp(left, t.value, right, t.line, t.col)
        return left

    def parse_unary(self):
        t = self.current_token()
        if t and t.type == 'OPERATOR' and t.value in ['not', '-']:
            self.consume()
            return UnaryOp(t.value, self.parse_unary(), t.line, t.col)
        return self.parse_primary()

    def get_precedence(self, op):
        if op in ['==','!=','<','>','<=','>=']: return 0
        if op in ['+','-']: return 1
        if op in ['*','/','%']: return 2
        return -1

    def parse_primary(self):
        t = self.current_token()
        if not t:
            raise MabaSyntaxError(self.tokens[-1].line if self.tokens else 1, 1, "\u671f\u671b\u8868\u8fbe\u5f0f")

        # in 输入函数 (in is both a KEYWORD for for-in and a builtin input function)
        if t.type == 'KEYWORD' and t.value == 'in':
            self.consume()
            if self.current_token() and self.current_token().type == 'LPAREN':
                self.consume()
                p = self.parse_expression()
                self.consume('RPAREN')
                return InFunction(p, t.line, t.col)
            elif self.current_token() and self.current_token().type == 'STRING':
                return InFunction(self.consume('STRING').value, t.line, t.col)
            else:
                # This is 'in' used in for loop context - shouldn't reach here normally
                # but just in case, treat as error
                raise MabaSyntaxError(t.line, t.col, "\u610f\u5916\u7684 'in' \u5173\u952e\u5b57", t.value)

        if t.type == 'IDENTIFIER' and self.peek() and self.peek().type == 'LPAREN':
            return self.parse_function_call()

        if t.type == 'LBRACKET':
            return self.parse_list_literal()
        if t.type == 'LBRACE':
            return self.parse_dict_literal()
        if t.type == 'BOOLEAN':
            self.consume(); return t.value
        if t.type == 'NONE':
            self.consume(); return None
        if t.type == 'STRING':
            self.consume(); return t.value
        if t.type in ['INT', 'FLOAT']:
            self.consume(); return t.value
        if t.type == 'IDENTIFIER':
            vn = t.value
            self.consume()
            if self.current_token() and self.current_token().type == 'LBRACKET':
                return self.parse_list_index(vn, t)
            if self.current_token() and self.current_token().type == 'DOT':
                return self.parse_method(vn, t)
            return VarReference(vn, t.line, t.col)
        if t.type == 'LPAREN':
            self.consume()
            expr = self.parse_expression()
            self.consume('RPAREN')
            return expr

        raise MabaSyntaxError(t.line, t.col, f"\u610f\u5916\u7684 token '{t.value}'", t.value)

    def parse_list_literal(self):
        t = self.current_token()
        self.consume('LBRACKET')
        elems = []
        if self.current_token() and self.current_token().type != 'RBRACKET':
            while True:
                elems.append(self.parse_expression())
                if self.current_token() and self.current_token().type == 'OPERATOR' and self.current_token().value == ',':
                    self.consume(); continue
                break
        self.consume('RBRACKET')
        return ListLiteral(elems, t.line, t.col)

    def parse_dict_literal(self):
        t = self.current_token()
        self.consume('LBRACE')
        pairs = []
        if self.current_token() and self.current_token().type != 'RBRACE':
            while True:
                k = self.parse_expression()
                self.consume('COLON')
                v = self.parse_expression()
                pairs.append((k, v))
                if self.current_token() and self.current_token().type == 'OPERATOR' and self.current_token().value == ',':
                    self.consume(); continue
                break
        self.consume('RBRACE')
        return DictionaryLiteral(pairs, t.line, t.col)

    def parse_list_index(self, var_name, tok):
        self.consume('LBRACKET')
        indices = []
        while True:
            ct = self.current_token()
            if ct and ct.type == 'IDENTIFIER':
                iname = self.consume().value
                if iname in ['low','high','zhong','left','right','mid']:
                    indices.append(('keyword', iname))
                else:
                    indices.append(('var', iname))
            elif ct and ct.type in ['INT','FLOAT']:
                indices.append(('value', self.consume().value))
            elif ct and ct.type == 'STRING':
                indices.append(('value', self.consume().value))
            else:
                indices.append(('expr', self.parse_expression()))
            if self.current_token() and self.current_token().type == 'OPERATOR' and self.current_token().value == ',':
                self.consume(); continue
            break
        self.consume('RBRACKET')
        return ListIndex(VarReference(var_name, tok.line, tok.col), indices, tok.line, tok.col)

    def parse_method(self, var_name, tok):
        obj = VarReference(var_name, tok.line, tok.col)
        self.consume('DOT')
        method = self.consume('IDENTIFIER').value
        self.consume('LPAREN')
        args = []
        if self.current_token() and self.current_token().type != 'RPAREN':
            while True:
                args.append(self.parse_expression())
                if self.current_token() and self.current_token().type == 'OPERATOR' and self.current_token().value == ',':
                    self.consume(); continue
                break
        self.consume('RPAREN')
        return StringMethod(obj, method, args, tok.line, tok.col)

# ========== 解释器 ==========
class MaboInterpreter:
    def __init__(self, interactive=False):
        self.variables = {}
        self.functions = {}
        self.output = []
        self.current_return = None
        self.interactive = interactive
        self.loop_break = False
        self.loop_continue = False
        self.stdout_capture = None  # for IDE capture
        self._stop_flag = False  # for safe thread stop

    def interpret(self, ast, local_vars=None):
        if self._stop_flag:
            raise RuntimeError("运行已被用户停止")

        if isinstance(ast, Program):
            for stmt in ast.statements:
                if self._stop_flag:
                    raise RuntimeError("运行已被用户停止")
                self.interpret(stmt, local_vars)
                if self.current_return is not None: break
                if self.loop_break:
                    self.loop_break = False; break
                if self.loop_continue:
                    self.loop_continue = False; continue
            return None

        if isinstance(ast, BreakStatement):
            self.loop_break = True; return None
        if isinstance(ast, ContinueStatement):
            self.loop_continue = True; return None

        if isinstance(ast, CompoundAssign):
            return self._eval_compound(ast, local_vars)
        if isinstance(ast, IncDec):
            return self._eval_incdec(ast, local_vars)

        if isinstance(ast, Declaration):
            val = self.interpret(ast.value, local_vars)
            if ast.var_type == 'zheng' and not isinstance(val, int):
                raise RuntimeError(f"\u6574\u6570\u7c7b\u578b\u53ea\u80fd\u8d4b\u503c\u6574\u6570\uff0c\u5f97\u5230 {type(val).__name__}")
            if ast.var_type == 'xiao' and not isinstance(val, (int, float)):
                raise RuntimeError(f"\u5c0f\u6570\u7c7b\u578b\u53ea\u80fd\u8d4b\u503c\u6570\u5b57\uff0c\u5f97\u5230 {type(val).__name__}")
            if ast.var_type == 'fu' and not isinstance(val, str):
                raise RuntimeError(f"\u5b57\u7b26\u4e32\u7c7b\u578b\u53ea\u80fd\u8d4b\u503c\u5b57\u7b26\u4e32\uff0c\u5f97\u5230 {type(val).__name__}")
            if ast.var_type == 'xiao' and isinstance(val, int): val = float(val)
            self._set_var(ast.var_name, val, local_vars)
            return val

        if isinstance(ast, Assignment):
            val = self.interpret(ast.value, local_vars)
            self._set_var(ast.var_name, val, local_vars)
            return val

        if isinstance(ast, BinaryOp):
            l = self.interpret(ast.left, local_vars)
            r = self.interpret(ast.right, local_vars)
            ops = {'+': lambda: l+r, '-': lambda: l-r, '*': lambda: l*r,
                   '%': lambda: l%r, '<': lambda: l<r, '>': lambda: l>r,
                   '<=': lambda: l<=r, '>=': lambda: l>=r, '==': lambda: l==r,
                   '!=': lambda: l!=r, 'and': lambda: l and r, 'or': lambda: l or r}
            if ast.operator == '/':
                if r == 0: raise RuntimeError("\u9664\u96f6\u9519\u8bef")
                return l / r
            if ast.operator in ops: return ops[ast.operator]()
            raise RuntimeError(f"\u672a\u77e5\u8fd0\u7b97\u7b26 '{ast.operator}'")

        if isinstance(ast, UnaryOp):
            od = self.interpret(ast.operand, local_vars)
            return (not od) if ast.operator == 'not' else -od

        if isinstance(ast, IfStatement):
            if self.interpret(ast.condition, local_vars):
                for s in ast.true_branch: self.interpret(s, local_vars)
            else:
                done = False
                for ec, eb in ast.elif_branches:
                    if self.interpret(ec, local_vars):
                        for s in eb: self.interpret(s, local_vars)
                        done = True; break
                if not done and ast.false_branch:
                    for s in ast.false_branch: self.interpret(s, local_vars)
            return None

        if isinstance(ast, WhileStatement):
            cnt = 0
            while self.interpret(ast.condition, local_vars) and cnt < 10000:
                if self._stop_flag:
                    raise RuntimeError("运行已被用户停止")
                self.loop_break = False; self.loop_continue = False
                for s in ast.body:
                    self.interpret(s, local_vars)
                    if self.loop_break or self.current_return is not None: break
                    if self.loop_continue: break
                if self.loop_break or self.current_return is not None: break
                cnt += 1
            if cnt >= 10000: raise RuntimeError("\u5faa\u73af\u8d85\u8fc7\u6700\u5927\u6b21\u6570")
            return None

        if isinstance(ast, ForStatement):
            items = self.interpret(ast.iterable, local_vars)
            if isinstance(items, range): items = list(items)
            elif isinstance(items, str): items = list(items)
            if not isinstance(items, list):
                raise RuntimeError(f"\u4e0d\u80fd\u904d\u5386 {type(items).__name__} \u7c7b\u578b")
            if len(items) > 100000:
                raise RuntimeError("\u5faa\u73af\u6b21\u6570\u8fc7\u591a\uff08\u4e0a\u9650 100000\uff09")
            for item in items:
                if self._stop_flag:
                    raise RuntimeError("运行已被用户停止")
                self._set_var(ast.iterator, item, local_vars)
                self.loop_break = False; self.loop_continue = False
                for s in ast.body:
                    self.interpret(s, local_vars)
                    if self.loop_break or self.current_return is not None: break
                    if self.loop_continue: break
                if self.loop_break or self.current_return is not None: break
            return None

        if isinstance(ast, FunctionDef):
            self.functions[ast.name] = ast
            return None

        if isinstance(ast, FunctionCall):
            return self._eval_call(ast, local_vars)

        if isinstance(ast, ReturnStatement):
            self.current_return = self.interpret(ast.value, local_vars) if ast.value is not None else None
            return self.current_return

        if isinstance(ast, OutStatement):
            vals = [str(self.interpret(v, local_vars)) for v in ast.values]
            out_str = ''.join(vals)
            self.output.append(out_str)
            if self.stdout_capture is not None:
                self.stdout_capture.write(out_str + '\n')
            else:
                print(out_str)
            return None

        if isinstance(ast, InFunction):
            prompt = self.interpret(ast.prompt, local_vars) if isinstance(ast.prompt, AST) else ast.prompt
            val = input(prompt)
            try:
                return float(val) if '.' in val else int(val)
            except ValueError:
                return val

        if isinstance(ast, VarReference):
            v = self._get_var(ast.name, local_vars)
            if v is not None: return v
            if ast.name in self.functions: return ast.name
            sug = suggest_word(ast.name)
            msg = f"\u53d8\u91cf '{ast.name}' \u672a\u5b9a\u4e49"
            if sug: msg += f"\n  \u60a8\u662f\u4e0d\u662f\u60f3\u5199 '{sug}'\uff1f"
            raise RuntimeError(msg)

        if isinstance(ast, ListLiteral):
            return [self.interpret(e, local_vars) for e in ast.elements]
        if isinstance(ast, DictionaryLiteral):
            return {self.interpret(k, local_vars): self.interpret(v, local_vars) for k, v in ast.pairs}

        if isinstance(ast, ListIndex):
            return self._eval_list_index(ast, local_vars)
        if isinstance(ast, StringMethod):
            return self._eval_string_method(ast, local_vars)
        if isinstance(ast, (int, float, str, bool, type(None))):
            return ast
        return None

    def _set_var(self, name, val, local_vars):
        if local_vars is not None and name in local_vars:
            local_vars[name] = val
        else:
            self.variables[name] = val

    def _get_var(self, name, local_vars):
        if local_vars and name in local_vars: return local_vars[name]
        if name in self.variables: return self.variables[name]
        return None

    def _eval_compound(self, ast, local_vars):
        cur = self._get_var(ast.var_name, local_vars)
        if cur is None and ast.var_name not in self.variables:
            raise RuntimeError(f"\u53d8\u91cf '{ast.var_name}' \u672a\u5b9a\u4e49")
        val = self.interpret(ast.value, local_vars)
        ops = {'+': cur+val, '-': cur-val, '*': cur*val}
        if ast.operator == '+=': r = cur + val
        elif ast.operator == '-=': r = cur - val
        elif ast.operator == '*=': r = cur * val
        elif ast.operator == '/=':
            if val == 0: raise RuntimeError("\u9664\u96f6\u9519\u8bef")
            r = cur / val
        else: raise RuntimeError(f"\u672a\u77e5\u8fd0\u7b97\u7b26 '{ast.operator}'")
        self._set_var(ast.var_name, r, local_vars)
        return r

    def _eval_incdec(self, ast, local_vars):
        cur = self._get_var(ast.var_name, local_vars)
        if cur is None and ast.var_name not in self.variables:
            raise RuntimeError(f"\u53d8\u91cf '{ast.var_name}' \u672a\u5b9a\u4e49")
        r = cur + 1 if ast.operator == '++' else cur - 1
        self._set_var(ast.var_name, r, local_vars)
        return r

    def _eval_call(self, ast, local_vars):
        # 内置函数
        builtin = self._builtin_call(ast, local_vars)
        if builtin is not None: return builtin

        if ast.name not in self.functions:
            sug = suggest_word(ast.name)
            msg = f"\u51fd\u6570 '{ast.name}' \u672a\u5b9a\u4e49"
            if sug: msg += f"\n  \u60a8\u662f\u4e0d\u662f\u60f3\u5199 '{sug}'\uff1f"
            raise RuntimeError(msg)

        func = self.functions[ast.name]
        args_dict = {}
        for i, arg in enumerate(ast.args):
            if i >= len(func.params):
                raise RuntimeError(f"\u51fd\u6570 '{ast.name}' \u53c2\u6570\u6570\u91cf\u4e0d\u5339\u914d")
            args_dict[func.params[i]] = self.interpret(arg, local_vars)
        for kn, kv in ast.kwargs:
            if kn not in func.params:
                raise RuntimeError(f"\u51fd\u6570 '{ast.name}' \u6ca1\u6709\u53c2\u6570 '{kn}'")
            args_dict[kn] = self.interpret(kv, local_vars)
        for param, default in zip(func.params, func.defaults):
            if param not in args_dict:
                if default is not None: args_dict[param] = self.interpret(default, local_vars)
                else: raise RuntimeError(f"\u7f3a\u5c11\u5fc5\u9700\u53c2\u6570 '{param}'")

        old_ret = self.current_return
        self.current_return = None
        for stmt in func.body:
            self.interpret(stmt, args_dict.copy())
            if self.current_return is not None: break
        result = self.current_return
        self.current_return = old_ret
        return result

    def _builtin_call(self, ast, local_vars):
        name = ast.name
        if name == 'len':
            return len(self.interpret(ast.args[0], local_vars))
        if name == 'type':
            obj = self.interpret(ast.args[0], local_vars)
            return {int:"\u6574\u6570", float:"\u5c0f\u6570", str:"\u5b57\u7b26\u4e32",
                    list:"\u5217\u8868", dict:"\u5b57\u5178", bool:"\u5e03\u5c14\u503c",
                    type(None):"\u7a7a\u503c"}.get(type(obj), type(obj).__name__)
        if name == 'str': return str(self.interpret(ast.args[0], local_vars))
        if name == 'int': return int(self.interpret(ast.args[0], local_vars))
        if name == 'float': return float(self.interpret(ast.args[0], local_vars))
        if name == 'abs': return abs(self.interpret(ast.args[0], local_vars))
        if name == 'max':
            return max([self.interpret(a, local_vars) for a in ast.args])
        if name == 'min':
            return min([self.interpret(a, local_vars) for a in ast.args])
        if name == 'sum':
            return sum(self.interpret(ast.args[0], local_vars))
        if name == 'round': return round(self.interpret(ast.args[0], local_vars))
        if name == 'sqrt':
            auto_import('math'); return math.sqrt(self.interpret(ast.args[0], local_vars))
        if name == 'pow':
            auto_import('math')
            return math.pow(self.interpret(ast.args[0], local_vars), self.interpret(ast.args[1], local_vars))
        if name == 'range':
            if len(ast.args) == 1: return range(self.interpret(ast.args[0], local_vars))
            return range(self.interpret(ast.args[0], local_vars), self.interpret(ast.args[1], local_vars))
        if name == 'random':
            auto_import('random')
            if len(ast.args) == 2:
                return random.randint(self.interpret(ast.args[0], local_vars), self.interpret(ast.args[1], local_vars))
            return random.random()
        if name == 'randint':
            auto_import('random')
            return random.randint(self.interpret(ast.args[0], local_vars), self.interpret(ast.args[1], local_vars))
        if name == 'choice':
            auto_import('random')
            return random.choice([self.interpret(a, local_vars) for a in ast.args])
        if name == 'shuffle':
            auto_import('random')
            obj = self.interpret(ast.args[0], local_vars)
            if isinstance(obj, list): random.shuffle(obj)
            return obj
        if name == 'time':
            auto_import('datetime'); return __import__('datetime').datetime.now().strftime("%H:%M:%S")
        if name == 'date':
            auto_import('datetime'); return __import__('datetime').datetime.now().strftime("%Y-%m-%d")
        if name == 'datetime':
            auto_import('datetime'); return __import__('datetime').datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if name == 'read_file':
            fn = self.interpret(ast.args[0], local_vars)
            try:
                with open(fn, 'r', encoding='utf-8') as f: return f.read()
            except FileNotFoundError:
                raise RuntimeError(f"\u6587\u4ef6 '{fn}' \u4e0d\u5b58\u5728")
        if name == 'write_file':
            fn = self.interpret(ast.args[0], local_vars)
            ct = self.interpret(ast.args[1], local_vars)
            with open(fn, 'w', encoding='utf-8') as f: f.write(str(ct))
            return True
        if name == 'append_file':
            fn = self.interpret(ast.args[0], local_vars)
            ct = self.interpret(ast.args[1], local_vars)
            with open(fn, 'a', encoding='utf-8') as f: f.write(str(ct))
            return True
        if name == 'clean': return None
        if name == 'shili':
            self._run_shili(); return None
        return None  # not a builtin

    def _eval_list_index(self, ast, local_vars):
        obj = self.interpret(ast.list_expr, local_vars)
        if not isinstance(obj, list):
            raise RuntimeError("\u53ea\u6709\u5217\u8868\u652f\u6301\u7d22\u5f15\u8bbf\u95ee")
        results = []
        for itype, ival in ast.indices:
            if itype == 'keyword':
                if ival in ['low','left']: results.append(obj[0])
                elif ival in ['high','right']: results.append(obj[-1])
                elif ival in ['zhong','mid']: results.append(obj[len(obj)//2])
            elif itype == 'value':
                if not isinstance(ival, int): raise RuntimeError("\u7d22\u5f15\u5fc5\u987b\u662f\u6574\u6570")
                results.append(obj[ival])
            elif itype == 'var':
                idx = self._get_var(ival, local_vars)
                if idx is None: raise RuntimeError(f"\u53d8\u91cf '{ival}' \u672a\u5b9a\u4e49")
                results.append(obj[idx])
            else:
                idx = self.interpret(ival, local_vars)
                results.append(obj[idx])
        return results[0] if len(results) == 1 else results

    def _eval_string_method(self, ast, local_vars):
        obj = self.interpret(ast.obj, local_vars)
        args = [self.interpret(a, local_vars) for a in ast.args]
        m = ast.method
        if isinstance(obj, str):
            if m == 'upper': return obj.upper()
            if m == 'lower': return obj.lower()
            if m == 'strip': return obj.strip()
            if m == 'split': return obj.split(args[0] if args else None)
            if m == 'replace':
                if len(args) < 2: raise RuntimeError("replace() \u9700\u8981\u81f3\u5c11 2 \u4e2a\u53c2\u6570")
                return obj.replace(args[0], args[1])
            if m == 'startswith': return obj.startswith(args[0]) if args else False
            if m == 'endswith': return obj.endswith(args[0]) if args else False
            if m == 'find': return obj.find(args[0]) if args else -1
            if m == 'len': return len(obj)
        if isinstance(obj, list):
            if m == 'append': obj.append(args[0] if args else None); return None
            if m == 'pop': return obj.pop(int(args[0])) if args else obj.pop()
            if m == 'reverse': obj.reverse(); return obj
            if m == 'sort': obj.sort(); return obj
            if m == 'len': return len(obj)
        raise RuntimeError(f"\u672a\u77e5\u65b9\u6cd5 '{m}'")

    def _run_shili(self):
        self.output.append("Mabo \u793a\u4f8b - \u6e29\u5ea6\u8f6c\u6362\u5668")

    def get_output(self):
        return '\n'.join(self.output)


# ============================================================================
#                          MABO IDE GUI
# ============================================================================

# ========== 自动补全词库 ==========
MABO_KEYWORDS = [
    "zheng", "xiao", "fu", "list", "dict",
    "if", "else", "elif", "while", "for", "def", "return",
    "break", "continue", "in", "and", "or", "not",
    "True", "False", "None", "out", "len",
    "abs", "max", "min", "sum", "sqrt", "pow", "round",
    "read_file", "write_file", "append_file",
    "range", "type", "str", "int", "float",
    "random", "randint", "choice", "shuffle",
    "time", "date", "datetime",
    "upper", "lower", "strip", "split", "replace",
    "append", "pop", "reverse", "sort",
    "shili", "clean",
]

# ========== 语法高亮 ==========
class MaboHighlighter(QSyntaxHighlighter):
    def __init__(self, parent=None, dark=True):
        super().__init__(parent)
        self.rules = []
        c_key = "#CC7832" if dark else "#7F0055"
        c_str = "#6A8759" if dark else "#2E7D32"
        c_cmt = "#808080" if dark else "#9E9E9E"
        c_num = "#6897BB" if dark else "#1565C0"
        c_type = "#FFC66D" if dark else "#E65100"
        c_builtin = "#A9B7C6" if dark else "#555555"

        keyword_fmt = QTextCharFormat()
        keyword_fmt.setForeground(QColor(c_key))
        keyword_fmt.setFontWeight(QFont.Weight.Bold)

        type_fmt = QTextCharFormat()
        type_fmt.setForeground(QColor(c_type))
        type_fmt.setFontWeight(QFont.Weight.Bold)

        string_fmt = QTextCharFormat()
        string_fmt.setForeground(QColor(c_str))

        comment_fmt = QTextCharFormat()
        comment_fmt.setForeground(QColor(c_cmt))
        comment_fmt.setFontItalic(True)

        num_fmt = QTextCharFormat()
        num_fmt.setForeground(QColor(c_num))

        builtin_fmt = QTextCharFormat()
        builtin_fmt.setForeground(QColor(c_builtin))

        core_kw = r'\b(if|else|elif|while|for|def|return|break|continue|and|or|not|in)\b'
        type_kw = r'\b(zheng|xiao|fu|list|dict)\b'
        builtin_kw = r'\b(out|len|type|str|int|float|range|abs|max|min|sum|sqrt|pow|round|random|randint|choice|shuffle|time|date|datetime|read_file|write_file|append_file|shili|clean|True|False|None)\b'

        self.rules.append((re.compile(core_kw), keyword_fmt))
        self.rules.append((re.compile(type_kw), type_fmt))
        self.rules.append((re.compile(builtin_kw), builtin_fmt))
        self.rules.append((re.compile(r'"[^"]*"'), string_fmt))
        self.rules.append((re.compile(r"'[^']*'"), string_fmt))
        self.rules.append((re.compile(r"#.*"), comment_fmt))
        self.rules.append((re.compile(r"\b\d+\.?\d*\b"), num_fmt))

    def highlightBlock(self, text):
        for pattern, fmt in self.rules:
            for match in pattern.finditer(text):
                self.setFormat(match.start(), match.end() - match.start(), fmt)

# ========== 行号区域 ==========
class LineNumberArea(QWidget):
    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor
        self.setAutoFillBackground(True)

    def sizeHint(self):
        return QSize(self.editor.line_number_area_width(), 0)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(event.rect(), self.editor._line_number_bg())

        block = self.editor.firstVisibleBlock()
        block_number = block.blockNumber()
        top = round(self.editor.blockBoundingGeometry(block).translated(self.editor.contentOffset()).top())
        bottom = top + round(self.editor.blockBoundingRect(block).height())

        font = painter.font()
        font.setFamily("Consolas")
        font.setPointSize(10)
        painter.setFont(font)

        fg = self.editor._line_number_fg()
        painter.setPen(fg)

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                number = str(block_number + 1)
                painter.drawText(0, int(top), self.width() - 5,
                               int(self.editor.blockBoundingRect(block).height()),
                               Qt.AlignmentFlag.AlignRight, number)
            block = block.next()
            top = bottom
            bottom = top + round(self.editor.blockBoundingRect(block).height())
            block_number += 1

# ========== Mabo 编辑器 ==========
class MaboEditor(QPlainTextEdit):
    def __init__(self, dark=True, font_size=12, parent=None):
        super().__init__(parent)
        self.dark = dark
        self.font_size = font_size
        self.file_path = None  # associated file path

        self.line_number_area = LineNumberArea(self)
        self.setFont(QFont("Consolas", font_size))
        self.setTabStopDistance(self.fontMetrics().horizontalAdvance(' ') * 4)
        self.highlighter = MaboHighlighter(self.document(), dark=dark)

        # 自动补全
        self.completer = QCompleter(MABO_KEYWORDS)
        self.completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.completer.setWidget(self)
        self.completer.setCompletionMode(QCompleter.CompletionMode.UnfilteredPopupCompletion)
        self.completer.activated.connect(self._insert_completion)
        self.completion_pos = 0
        self._completion_model = QStringListModel()  # 持久化 model，避免 GC 回收

        self.blockCountChanged.connect(self._update_line_area_width)
        self.updateRequest.connect(self._update_line_area)
        self._update_line_area_width(0)

        self.set_theme(dark)

    def _line_number_bg(self):
        return QColor("#313335") if self.dark else QColor("#F0F0F0")

    def _line_number_fg(self):
        return QColor("#858585") if self.dark else QColor("#A0A0A0")

    def line_number_area_width(self):
        digits = len(str(max(1, self.blockCount())))
        return 15 + self.fontMetrics().horizontalAdvance('9') * digits

    def _update_line_area_width(self, new_block_count):
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)

    def _update_line_area(self, rect, dy):
        if dy:
            self.line_number_area.scroll(0, dy)
        else:
            self.line_number_area.update(0, rect.y(), self.line_number_area.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._update_line_area_width(0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        cr = self.contentsRect()
        self.line_number_area.setGeometry(QRect(cr.left(), cr.top(), self.line_number_area_width(), cr.height()))

    def set_theme(self, dark):
        self.dark = dark
        if dark:
            self.setStyleSheet(
                "QPlainTextEdit { background: #2B2B2B; color: #A9B7C6; "
                "selection-background-color: #214283; selection-color: #FFFFFF; }")
        else:
            self.setStyleSheet(
                "QPlainTextEdit { background: #FFFFFF; color: #000000; "
                "selection-background-color: #B4D5FF; selection-color: #000000; }")
        self.highlighter = MaboHighlighter(self.document(), dark=dark)
        self.highlighter.rehighlight()
        self.line_number_area.update()

    # ---- 自动补全 & 自动补括号 ----
    # 括号对映射
    _BRACKET_PAIRS = {
        '(': ')', '[': ']', '{': '}', '"': '"', "'": "'",
    }
    # 自动跳过的闭合括号
    _CLOSE_BRACKETS = {')', ']', '}'}

    def keyPressEvent(self, event):
        if self.completer and self.completer.popup().isVisible():
            key = event.key()

            # Enter/Tab: 插入当前选中项
            if key in (Qt.Key.Key_Enter, Qt.Key.Key_Return, Qt.Key.Key_Tab):
                index = self.completer.popup().currentIndex()
                if index.isValid():
                    completion = index.data(Qt.ItemDataRole.DisplayRole)
                    self._insert_completion(completion)
                self.completer.popup().hide()
                return

            # Escape: 关闭弹框
            if key == Qt.Key.Key_Escape:
                self.completer.popup().hide()
                return

            # Up/Down: 导航弹框列表
            if key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
                self.completer.popup().keyPressEvent(event)
                return

            # Backspace/Delete: 关闭弹框 → 处理按键 → 重新触发补全
            if key in (Qt.Key.Key_Backspace, Qt.Key.Key_Delete):
                self.completer.popup().hide()
                super().keyPressEvent(event)
                self._trigger_completion()
                return

            # 非字母输入: 关闭弹框，正常处理
            if not event.text() or not event.text().isalpha():
                self.completer.popup().hide()
                super().keyPressEvent(event)
                return

        # ---- 自动补括号 ----
        text = event.text()
        if text:
            # 输入闭合括号且光标后面就是同一个闭合括号 → 跳过，不重复输入
            if text in self._CLOSE_BRACKETS:
                cursor = self.textCursor()
                pos = cursor.position()
                cursor.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor, 1)
                if cursor.selectedText() == text:
                    # 跳过这个闭合括号，光标右移
                    cursor.clearSelection()
                    self.setTextCursor(cursor)
                    return

            # 输入开括号 → 自动补上闭合括号
            if text in self._BRACKET_PAIRS:
                close = self._BRACKET_PAIRS[text]
                cursor = self.textCursor()
                # 先插入开括号
                super().keyPressEvent(event)
                # 再插入闭合括号
                cursor.insertText(close)
                # 光标回退到中间（开括号和闭合括号之间）
                cursor.setPosition(cursor.position() - 1)
                self.setTextCursor(cursor)
                return

        # 正常处理按键
        super().keyPressEvent(event)

        # 字母键触发补全
        if event.text() and event.text().isalpha():
            self._trigger_completion()

    def _trigger_completion(self):
        """触发自动补全弹框"""
        cursor = self.textCursor()
        cursor.select(QTextCursor.SelectionType.WordUnderCursor)
        word = cursor.selectedText()
        if len(word) < 1:
            if self.completer and self.completer.popup().isVisible():
                self.completer.popup().hide()
            return

        matches = [w for w in MABO_KEYWORDS if w.startswith(word) and w != word]
        if not matches:
            if self.completer and self.completer.popup().isVisible():
                self.completer.popup().hide()
            return

        self.completion_pos = cursor.selectionStart()
        self._completion_model.setStringList(matches)
        self.completer.setModel(self._completion_model)
        self.completer.setCompletionPrefix(word)

        rect = self.cursorRect()
        rect.setWidth(self.completer.popup().sizeHintForColumn(0) + self.completer.popup().verticalScrollBar().sizeHint().width())
        self.completer.complete(rect)

        # 默认选中第一项
        self.completer.popup().setCurrentIndex(
            self.completer.popup().model().index(0, 0)
        )

    def _insert_completion(self, text):
        cursor = self.textCursor()
        cursor.select(QTextCursor.SelectionType.WordUnderCursor)
        cursor.insertText(text)
        self.setTextCursor(cursor)

# ========== Mabo 交互式控制台（匹配 MaboV2.0 解释器风格）==========
class MaboREPL(QPlainTextEdit):
    """交互式 Mabo REPL — 直接在输出区打字，匹配 MaboV2.0 解释器风格
    提示符 >>> / ... ，支持多行块输入，内置命令 vars()/help()/clean()/save/load/list
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFont(QFont("Consolas", 11))
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)

        # 持久化解释器实例
        self.interpreter = MaboInterpreter(interactive=True)

        # 多行块输入
        self.buffer = []
        self.in_block = False
        self.source_lines = []
        self.line_offset = 0

        # 历史命令
        self.history = []
        self.history_index = 0

        # 输入起始位置（用户只能在此之后打字）
        self._input_start = 0

        # 是否已退出
        self._exited = False

        # 欢迎信息
        welcome = (
            "Mabo Language v2.0 (Mabo 语言)\n"
            '输入 "exit()" 或 "quit()" 退出\n'
            '输入 "vars()" 查看所有变量\n'
            '输入 "help()" 查看帮助\n'
            '输入 "shili()" 运行示例程序\n'
            '输入 "clean()" 清屏（保留变量）\n'
            '输入 "save 文件名.mabo" 保存代码\n'
            '输入 "load 文件名.mabo" 加载代码\n'
            '输入 "list" 查看已保存的文件\n\n'
        )
        self.setPlainText(welcome)
        self._show_prompt()

    # -------------------- 提示符 --------------------
    def _show_prompt(self):
        if self._exited:
            return
        prompt = "... " if self.in_block else ">>> "
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(prompt)
        self.setTextCursor(cursor)
        self._input_start = cursor.position()
        self.ensureCursorVisible()

    # -------------------- 键盘事件 --------------------
    def keyPressEvent(self, event):
        if self._exited:
            return

        key = event.key()
        cursor = self.textCursor()

        # Ctrl+C — 中断当前块输入
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier and key == Qt.Key.Key_C:
            self.buffer = []
            self.in_block = False
            cursor.movePosition(QTextCursor.MoveOperation.End)
            cursor.insertText("\nKeyboardInterrupt\n")
            self.setTextCursor(cursor)
            self._show_prompt()
            return

        # Enter — 提交当前行
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            cursor.movePosition(QTextCursor.MoveOperation.End)
            cursor.setPosition(self._input_start, QTextCursor.MoveMode.KeepAnchor)
            line = cursor.selectedText()

            if line.strip():
                self.history.append(line)
                self.history_index = len(self.history)

            cursor.movePosition(QTextCursor.MoveOperation.End)
            cursor.insertText("\n")
            self.setTextCursor(cursor)
            self._process_input(line)
            return

        # Backspace — 不能删除到提示符前
        if key == Qt.Key.Key_Backspace:
            if cursor.position() <= self._input_start:
                return
            if cursor.hasSelection():
                sel_start = min(cursor.selectionStart(), cursor.selectionEnd())
                if sel_start < self._input_start:
                    return
            super().keyPressEvent(event)
            return

        # Delete — 不能删除提示符前
        if key == Qt.Key.Key_Delete:
            if cursor.position() < self._input_start:
                return
            super().keyPressEvent(event)
            return

        # Up — 历史上翻
        if key == Qt.Key.Key_Up:
            if self.history and self.history_index > 0:
                self.history_index -= 1
                self._replace_input(self.history[self.history_index])
            return

        # Down — 历史下翻
        if key == Qt.Key.Key_Down:
            if self.history_index < len(self.history) - 1:
                self.history_index += 1
                self._replace_input(self.history[self.history_index])
            else:
                self.history_index = len(self.history)
                self._replace_input("")
            return

        # Home — 跳到提示符后
        if key == Qt.Key.Key_Home:
            cursor.setPosition(self._input_start)
            self.setTextCursor(cursor)
            return

        # Left — 不能越过提示符
        if key == Qt.Key.Key_Left:
            if cursor.position() <= self._input_start:
                return
            super().keyPressEvent(event)
            return

        # 不允许在提示符前打字
        if event.text() and cursor.position() < self._input_start:
            cursor.movePosition(QTextCursor.MoveOperation.End)
            self.setTextCursor(cursor)

        super().keyPressEvent(event)

    def _replace_input(self, text):
        """替换当前输入行"""
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.setPosition(self._input_start, QTextCursor.MoveMode.KeepAnchor)
        cursor.removeSelectedText()
        cursor.insertText(text)
        self.setTextCursor(cursor)

    # -------------------- 输入处理 --------------------
    def _process_input(self, line):
        line_strip = line.strip()

        # ---- 退出 ----
        if line_strip in ('exit()', 'quit()'):
            self.appendPlainText("再见！")
            self._exited = True
            self.setReadOnly(True)
            return

        # ---- 查看变量 ----
        if line_strip == 'vars()':
            vars_dict = self.interpreter.variables
            if vars_dict:
                for key, value in vars_dict.items():
                    self.appendPlainText(f"{key} = {repr(value)}")
            else:
                self.appendPlainText("{}")
            self._show_prompt()
            return

        # ---- 帮助 ----
        if line_strip == 'help()':
            self.appendPlainText(self._help_text())
            self._show_prompt()
            return

        # ---- 运行示例 ----
        if line_strip == 'shili()':
            self._run_shili()
            self._show_prompt()
            return

        # ---- 清屏 ----
        if line_strip == 'clean()':
            self.line_offset += len(self.source_lines) if self.source_lines else 0
            self.clear()
            self.appendPlainText("Mabo Language v2.0 (Mabo 语言)")
            self.appendPlainText('输入 "exit()" 或 "quit()" 退出')
            self.appendPlainText('输入 "vars()" 查看所有变量')
            self.appendPlainText('输入 "help()" 查看帮助')
            self.appendPlainText('输入 "clean()" 清屏（保留变量）\n')
            self.source_lines = []
            self._show_prompt()
            return

        # ---- 保存代码 ----
        if line_strip.startswith('save '):
            filename = line_strip[5:].strip()
            if not filename:
                self.appendPlainText("错误: 请指定文件名，例如: save test.mabo")
            else:
                if not filename.endswith('.mabo'):
                    filename += '.mabo'
                code = '\n'.join(self.buffer) if self.buffer else ""
                self.buffer = []
                try:
                    with open(filename, 'w', encoding='utf-8') as f:
                        f.write(code)
                    self.appendPlainText(f"代码已保存到 {filename}")
                except Exception as e:
                    self.appendPlainText(f"保存失败: {e}")
            self._show_prompt()
            return

        # ---- 加载代码 ----
        if line_strip.startswith('load '):
            filename = line_strip[5:].strip()
            if not filename:
                self.appendPlainText("错误: 请指定文件名，例如: load test.mabo")
            else:
                if not filename.endswith('.mabo'):
                    filename += '.mabo'
                try:
                    with open(filename, 'r', encoding='utf-8') as f:
                        code = f.read()
                    self.appendPlainText(f"已加载 {filename}")
                    self.appendPlainText("-" * 40)
                    self.appendPlainText(code)
                    self.appendPlainText("-" * 40)
                    self.buffer = [code]
                    self._execute_buffer()
                except FileNotFoundError:
                    self.appendPlainText(f"文件 '{filename}' 不存在")
                except Exception as e:
                    self.appendPlainText(f"加载失败: {e}")
            self._show_prompt()
            return

        # ---- 列出文件 ----
        if line_strip == 'list':
            try:
                files = [f for f in os.listdir('.') if f.endswith('.mabo')]
                if files:
                    self.appendPlainText("已保存的 Mabo 文件:")
                    for f in files:
                        self.appendPlainText(f"  - {f}")
                else:
                    self.appendPlainText("没有找到 .mabo 文件")
            except Exception:
                self.appendPlainText("无法列出文件")
            self._show_prompt()
            return

        # ---- 多行块输入 ----
        self.buffer.append(line)

        if self.in_block:
            if line_strip in ('}', '｝'):
                self.in_block = False
                self._execute_buffer()
        else:
            if line_strip.endswith('{') or line_strip.endswith('｛'):
                self.in_block = True
            elif line_strip and not line_strip.startswith('#'):
                self._execute_buffer()

        self._show_prompt()

    def _execute_buffer(self):
        if not self.buffer:
            return
        code = '\n'.join(self.buffer)
        self.buffer = []
        self.source_lines = code.split('\n')

        buf = io.StringIO()
        self.interpreter.stdout_capture = buf
        try:
            lexer = Lexer(code)
            tokens = lexer.tokenize()
            parser = Parser(tokens, self.source_lines, self.line_offset)
            ast = parser.parse()
            self.interpreter.interpret(ast)

            captured = buf.getvalue()
            if captured:
                self.appendPlainText(captured.rstrip('\n'))
        except MabaSyntaxError as e:
            self.appendPlainText(e.format_error(self.source_lines, self.line_offset))
        except (SyntaxError, RuntimeError) as e:
            self.appendPlainText(f"错误: {e}")
        except Exception as e:
            if hasattr(e, 'format_error') and self.source_lines:
                self.appendPlainText(e.format_error(self.source_lines, self.line_offset))
            else:
                self.appendPlainText(f"错误: {e}")
            self.buffer = []
            self.in_block = False
        finally:
            buf.close()
            self.interpreter.stdout_capture = None

    def _run_shili(self):
        """运行示例程序 — 温度转换"""
        self.appendPlainText("\n" + "=" * 50)
        self.appendPlainText("Mabo 示例程序 - 温度转换器")
        self.appendPlainText("=" * 50)
        self.appendPlainText("（在 IDE 中请直接编写代码运行，此处为简化示例）")

    @staticmethod
    def _help_text():
        return """
Mabo 语言帮助
=============

基本语法:
  zheng:变量名 = 值     # 声明整数变量
  xiao:变量名 = 值      # 声明浮点数变量
  fu:变量名 = "值"      # 声明字符串变量
  变量名 = 值           # 赋值

条件:
  if 条件 { 语句 }
  elif 条件 { 语句 }
  else { 语句 }

循环:
  while 条件 { 语句 }
  for 变量 in 列表 { 语句 }

函数:
  def 函数名(参数) { 语句; return 返回值 }

内置命令:
  exit()  / quit()  - 退出
  vars()            - 查看变量
  help()            - 显示帮助
  clean()           - 清屏（保留变量）
  save 文件名.mabo  - 保存代码
  load 文件名.mabo  - 加载代码
  list              - 列出文件
"""

    def set_theme(self, dark):
        if dark:
            self.setStyleSheet(
                "QPlainTextEdit { background: #1E1E1E; color: #D4D4D4; "
                "border: none; padding: 4px; selection-background-color: #264F78; }")
        else:
            self.setStyleSheet(
                "QPlainTextEdit { background: #FFFFFF; color: #333333; "
                "border: 1px solid #DDD; padding: 4px; }")

# ========== 系统终端 ==========
class TerminalWidget(QPlainTextEdit):
    """嵌入式系统终端 — 直接在输出区打字，通过 QProcess 与 PowerShell/cmd 交互"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFont(QFont("Consolas", 11))
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.setPlaceholderText("启动终端中...")

        # QProcess
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.process.readyReadStandardOutput.connect(self._read_output)

        # 自动检测 shell
        import shutil
        self.shell_cmd = "powershell.exe" if shutil.which("powershell") else "cmd.exe"

        # 历史命令
        self.history = []
        self.history_index = 0

        # 用户输入起始位置
        self._input_start = 0

        self._start_shell()

    def _start_shell(self):
        self.process.start(self.shell_cmd)
        if not self.process.waitForStarted(3000):
            self.setPlainText(f"[错误] 无法启动 {self.shell_cmd}")
            return
        if "powershell" in self.shell_cmd.lower():
            self.process.write(
                b"chcp 65001 >$null; "
                b"[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
                b"$OutputEncoding = [System.Text.Encoding]::UTF8\n"
            )

    def _read_output(self):
        data = self.process.readAllStandardOutput().data()
        try:
            text = data.decode("gbk", errors="replace")
        except Exception:
            text = data.decode("utf-8", errors="replace")

        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(text)
        self.setTextCursor(cursor)
        self._input_start = cursor.position()
        self.ensureCursorVisible()

    # -------------------- 键盘事件 --------------------
    def keyPressEvent(self, event):
        if self.process.state() == QProcess.ProcessState.NotRunning:
            super().keyPressEvent(event)
            return

        key = event.key()
        cursor = self.textCursor()

        # Ctrl+C — 中断当前命令
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier and key == Qt.Key.Key_C:
            cursor.movePosition(QTextCursor.MoveOperation.End)
            cursor.insertText("^C\n")
            self.setTextCursor(cursor)
            self.process.write(b"\x03")  # SIGINT
            self._input_start = cursor.position()
            return

        # Enter — 发送命令
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            cursor.movePosition(QTextCursor.MoveOperation.End)
            cursor.setPosition(self._input_start, QTextCursor.MoveMode.KeepAnchor)
            line = cursor.selectedText()

            if line.strip():
                self.history.append(line)
                self.history_index = len(self.history)

            cursor.movePosition(QTextCursor.MoveOperation.End)
            cursor.insertText("\n")
            self.setTextCursor(cursor)
            self._input_start = cursor.position()

            self.process.write((line + "\n").encode("utf-8"))
            return

        # Backspace — 不能删除到输入起始前
        if key == Qt.Key.Key_Backspace:
            if cursor.position() <= self._input_start:
                return
            if cursor.hasSelection():
                sel_start = min(cursor.selectionStart(), cursor.selectionEnd())
                if sel_start < self._input_start:
                    return
            super().keyPressEvent(event)
            return

        # Delete
        if key == Qt.Key.Key_Delete:
            if cursor.position() < self._input_start:
                return
            super().keyPressEvent(event)
            return

        # Up — 历史上翻
        if key == Qt.Key.Key_Up:
            if self.history and self.history_index > 0:
                self.history_index -= 1
                self._replace_input(self.history[self.history_index])
            return

        # Down — 历史下翻
        if key == Qt.Key.Key_Down:
            if self.history_index < len(self.history) - 1:
                self.history_index += 1
                self._replace_input(self.history[self.history_index])
            else:
                self.history_index = len(self.history)
                self._replace_input("")
            return

        # Home — 跳到输入起始
        if key == Qt.Key.Key_Home:
            cursor.setPosition(self._input_start)
            self.setTextCursor(cursor)
            return

        # Left — 不能越过输入起始
        if key == Qt.Key.Key_Left:
            if cursor.position() <= self._input_start:
                return
            super().keyPressEvent(event)
            return

        # 不允许在输入起始前打字
        if event.text() and cursor.position() < self._input_start:
            cursor.movePosition(QTextCursor.MoveOperation.End)
            self.setTextCursor(cursor)

        super().keyPressEvent(event)

    def _replace_input(self, text):
        """替换当前输入行"""
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.setPosition(self._input_start, QTextCursor.MoveMode.KeepAnchor)
        cursor.removeSelectedText()
        cursor.insertText(text)
        self.setTextCursor(cursor)

    def set_theme(self, dark):
        if dark:
            self.setStyleSheet(
                "QPlainTextEdit { background: #0C0C0C; color: #CCCCCC; "
                "border: none; padding: 4px; selection-background-color: #264F78; }")
        else:
            self.setStyleSheet(
                "QPlainTextEdit { background: #FFFFFF; color: #000000; "
                "border: 1px solid #DDD; padding: 4px; }")

    def closeEvent(self, event):
        if self.process.state() != QProcess.ProcessState.NotRunning:
            self.process.kill()
            self.process.waitForFinished(2000)
        super().closeEvent(event)

# ========== 运行线程 ==========
class RunThread(QThread):
    output = pyqtSignal(str)
    error = pyqtSignal(str)
    finished_ok = pyqtSignal()

    def __init__(self, code, source_lines):
        super().__init__()
        self.code = code
        self.source_lines = source_lines
        self.interp = None  # 保留引用以便安全停止
        self._user_stop = False

    def stop(self):
        """安全停止：设置 flag 让解释器自行退出，不使用 terminate()"""
        self._user_stop = True
        if self.interp:
            self.interp._stop_flag = True

    def run(self):
        buf = io.StringIO()
        try:
            lexer = Lexer(self.code)
            tokens = lexer.tokenize()
            parser = Parser(tokens, self.source_lines, 0)
            ast = parser.parse()
            self.interp = MaboInterpreter(interactive=False)
            self.interp.stdout_capture = buf
            if self._user_stop:
                self.interp._stop_flag = True
            self.interp.interpret(ast)
            out = buf.getvalue()
            if out:
                self.output.emit(out)
            if self.interp.output:
                combined = '\n'.join(self.interp.output)
                if combined != out.rstrip('\n'):
                    pass
            if self._user_stop:
                self.error.emit("[已停止]")
            else:
                self.finished_ok.emit()
        except MabaSyntaxError as e:
            self.error.emit(e.format_error(self.source_lines, 0))
        except (SyntaxError, RuntimeError) as e:
            if self._user_stop:
                self.error.emit("[已停止]")
            else:
                self.error.emit(str(e))
        except Exception as e:
            self.error.emit(f"\u8fd0\u884c\u9519\u8bef: {e}")
        finally:
            buf.close()

# ========== 设置窗口 ==========
class SettingsDialog(QDialog):
    def __init__(self, is_dark, font_size, parent=None):
        super().__init__(parent)
        self.setWindowTitle("IDE \u8bbe\u7f6e")
        self.resize(320, 200)
        layout = QVBoxLayout(self)

        self.dark_cb = QCheckBox("\u542f\u7528\u6df1\u8272\u6a21\u5f0f")
        self.dark_cb.setChecked(is_dark)
        layout.addWidget(self.dark_cb)

        hl = QHBoxLayout()
        hl.addWidget(QLabel("\u5b57\u4f53\u5927\u5c0f:"))
        self.font_spin = QSpinBox()
        self.font_spin.setRange(8, 28)
        self.font_spin.setValue(font_size)
        hl.addWidget(self.font_spin)
        layout.addLayout(hl)

        btn_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    def is_dark_enabled(self): return self.dark_cb.isChecked()
    def get_font_size(self): return self.font_spin.value()

# ========== 主 IDE ==========
class MaboIDE(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Mabo IDE v2.0")
        self.resize(1400, 900)
        self.is_dark_mode = True
        self.font_size = 12
        self.workspace = os.getcwd()
        self.run_thread = None
        self._init_config()
        self.init_ui()
        self.statusBar().showMessage("\u5c31\u7eea | \u5185\u7f6e Mabo V2.0 \u89e3\u91ca\u5668 | F5 \u8fd0\u884c | Ctrl+S \u4fdd\u5b58")

    def _init_config(self):
        self.config_path = os.path.join(os.path.expanduser("~"), ".mabo_ide_config.json")
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    cfg = json.load(f)
                self.is_dark_mode = cfg.get('dark', True)
                self.font_size = cfg.get('font_size', 12)
                self.workspace = cfg.get('workspace', os.getcwd())
            except Exception:
                pass

    def _save_config(self):
        try:
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump({'dark': self.is_dark_mode, 'font_size': self.font_size, 'workspace': self.workspace}, f)
        except Exception:
            pass

    def init_ui(self):
        self.central = QWidget()
        self.setCentralWidget(self.central)
        self.main_layout = QVBoxLayout(self.central)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.init_menu()
        self.init_toolbar()
        self.init_panels()
        self.apply_theme(self.is_dark_mode)

    def init_menu(self):
        mb = self.menuBar()

        file_menu = mb.addMenu("\u6587\u4ef6(&F)")
        self._add_action(file_menu, "\u65b0\u5efa(&N)", self.add_tab, "Ctrl+N")
        self._add_action(file_menu, "\u6253\u5f00(&O)", self.open_file, "Ctrl+O")
        self._add_action(file_menu, "\u4fdd\u5b58(&S)", self.save_file, "Ctrl+S")
        file_menu.addSeparator()
        self._add_action(file_menu, "\u53e6\u5b58\u4e3a...", self.save_file_as, "Ctrl+Shift+S")

        run_menu = mb.addMenu("\u8fd0\u884c(&R)")
        self._add_action(run_menu, "\u8fd0\u884c(&R)", self.run_code, "F5")
        self._add_action(run_menu, "\u505c\u6b62", self.stop_run, "Shift+F5")
        self._add_action(run_menu, "\u683c\u5f0f\u5316\u4ee3\u7801", self.format_code, "Ctrl+Shift+F")

        view_menu = mb.addMenu("\u89c6\u56fe(&V)")
        self._add_action(view_menu, "\u5237\u65b0\u6587\u4ef6\u5217\u8868", self.refresh_file_list, "F2")
        self._add_action(view_menu, "\u6e05\u7a7a\u63a7\u5236\u53f0", self.clear_console, "Ctrl+L")

        proj_menu = mb.addMenu("\u9879\u76ee(&P)")
        self._add_action(proj_menu, "\u9009\u62e9\u5de5\u4f5c\u533a", self.select_workspace, "")

        set_menu = mb.addMenu("\u8bbe\u7f6e(&S)")
        self._add_action(set_menu, "\u6253\u5f00\u8bbe\u7f6e", self.open_settings, "Ctrl+,")

    def _add_action(self, menu, text, slot, shortcut):
        action = QAction(text, self)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
        action.triggered.connect(slot)
        menu.addAction(action)

    def init_toolbar(self):
        bar = QToolBar()
        bar.setMovable(False)
        bar.setIconSize(QSize(20, 20))
        self.addToolBar(bar)
        bar.addAction("\U0001f4cb \u65b0\u5efa", self.add_tab)
        bar.addAction("\u25b6 \u8fd0\u884c", self.run_code)
        bar.addAction("\u23f9 \u505c\u6b62", self.stop_run)
        bar.addSeparator()
        bar.addAction("\U0001f4be \u4fdd\u5b58", self.save_file)
        bar.addAction("\U0001f4c2 \u6253\u5f00", self.open_file)
        bar.addSeparator()
        bar.addAction("\U0001f500 \u683c\u5f0f\u5316", self.format_code)
        bar.addAction("\U0001f3e0 \u5de5\u4f5c\u533a", self.select_workspace)
        bar.addAction("\u2699 \u8bbe\u7f6e", self.open_settings)

    def init_panels(self):
        self.h_split = QSplitter(Qt.Orientation.Horizontal)
        self.main_layout.addWidget(self.h_split)

        # 左侧：文件列表
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(2, 2, 2, 2)
        left_label = QLabel("\U0001f4c1 \u6587\u4ef6")
        left_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        left_layout.addWidget(left_label)
        self.file_list = QListWidget()
        self.file_list.itemDoubleClicked.connect(self.open_from_list)
        left_layout.addWidget(self.file_list)
        self.h_split.addWidget(left_panel)

        # 右侧：编辑区 + 底部面板
        self.v_split = QSplitter(Qt.Orientation.Vertical)

        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.tabCloseRequested.connect(self._close_tab)
        self.v_split.addWidget(self.tabs)

        # --- 底部面板：三 Tab ---
        self.bottom_tabs = QTabWidget()
        self.bottom_tabs.setMaximumHeight(400)

        # Tab 1: 运行输出
        self.console = QPlainTextEdit()
        self.console.setReadOnly(True)
        self.console.setFont(QFont("Consolas", 11))
        self.bottom_tabs.addTab(self.console, "运行输出")

        # Tab 2: 终端
        self.terminal = TerminalWidget()
        self.bottom_tabs.addTab(self.terminal, "终端")

        # Tab 3: Mabo 控制台
        self.mabo_repl = MaboREPL()
        self.bottom_tabs.addTab(self.mabo_repl, "Mabo 控制台")

        self.v_split.addWidget(self.bottom_tabs)

        self.h_split.addWidget(self.v_split)
        self.h_split.setSizes([200, 1000])

        self.add_tab()
        self.refresh_file_list()

    def _close_tab(self, index):
        widget = self.tabs.widget(index)
        if widget:
            widget.deleteLater()
        self.tabs.removeTab(index)
        if self.tabs.count() == 0:
            self.add_tab()

    def refresh_file_list(self):
        self.file_list.clear()
        try:
            for name in sorted(os.listdir(self.workspace)):
                if name.endswith(".mabo") or name.endswith(".py"):
                    self.file_list.addItem(name)
        except FileNotFoundError:
            pass

    def apply_theme(self, dark):
        self.is_dark_mode = dark
        if dark:
            self.setStyleSheet("""
                QMainWindow { background: #3C3F41; }
                QMenuBar { background: #3C3F41; color: #BBBBBB; }
                QMenuBar::item:selected { background: #4B6EAF; }
                QMenu { background: #3C3F41; color: #BBBBBB; }
                QMenu::item:selected { background: #4B6EAF; }
                QToolBar { background: #3C3F41; border: none; spacing: 4px; }
                QToolBar QToolButton { color: #BBBBBB; padding: 4px 8px; }
                QTabWidget::pane { border: 1px solid #555; }
                QTabBar::tab { background: #3C3F41; color: #AAAAAA; padding: 6px 12px; border: 1px solid #555; }
                QTabBar::tab:selected { background: #4B6EAF; color: white; }
                QSplitter::handle { background: #555; }
                QListWidget { background: #313335; color: #A9B7C6; border: none; }
                QListWidget::item:selected { background: #4B6EAF; }
                QLabel { color: #BBBBBB; }
                QStatusBar { background: #3C3F41; color: #888; }
            """)
            self.console.setStyleSheet(
                "QPlainTextEdit { background: #1E1E1E; color: #D4D4D4; "
                "border: 1px solid #555; padding: 4px; }")
            self.bottom_tabs.setStyleSheet("""
                QTabWidget::pane { border: 1px solid #555; }
                QTabBar::tab { background: #3C3F41; color: #AAAAAA; padding: 6px 12px; border: 1px solid #555; }
                QTabBar::tab:selected { background: #4B6EAF; color: white; }
            """)
            self.terminal.set_theme(True)
            self.mabo_repl.set_theme(True)
        else:
            self.setStyleSheet("""
                QMainWindow { background: #F5F5F5; }
                QMenuBar { background: #F5F5F5; color: #333; }
                QMenu { background: #FFF; color: #333; }
                QMenu::item:selected { background: #E0E0E0; }
                QToolBar { background: #F5F5F5; border: none; spacing: 4px; }
                QTabBar::tab { background: #E8E8E8; color: #333; padding: 6px 12px; }
                QTabBar::tab:selected { background: #4B6EAF; color: white; }
                QListWidget { background: #FFF; color: #333; border: 1px solid #DDD; }
                QListWidget::item:selected { background: #4B6EAF; color: white; }
                QStatusBar { background: #F5F5F5; color: #666; }
            """)
            self.console.setStyleSheet(
                "QPlainTextEdit { background: #FFF; color: #333; "
                "border: 1px solid #DDD; padding: 4px; }")
            self.bottom_tabs.setStyleSheet("")
            self.terminal.set_theme(False)
            self.mabo_repl.set_theme(False)

        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            if isinstance(w, MaboEditor):
                w.set_theme(dark)
        self._save_config()

    # ==================== 功能 ====================
    def select_workspace(self):
        path = QFileDialog.getExistingDirectory(self, "\u9009\u62e9\u5de5\u4f5c\u6587\u4ef6\u5939", self.workspace)
        if path:
            self.workspace = path
            self.refresh_file_list()
            self.statusBar().showMessage(f"\u5de5\u4f5c\u533a\uff1a{path}")
            self._save_config()

    def open_settings(self):
        d = SettingsDialog(self.is_dark_mode, self.font_size, self)
        if d.exec():
            new_dark = d.is_dark_enabled()
            new_size = d.get_font_size()
            if new_dark != self.is_dark_mode:
                self.apply_theme(new_dark)
            if new_size != self.font_size:
                self.font_size = new_size
                for i in range(self.tabs.count()):
                    w = self.tabs.widget(i)
                    if isinstance(w, MaboEditor):
                        w.setFont(QFont("Consolas", new_size))
                self._save_config()

    def add_tab(self):
        ed = MaboEditor(dark=self.is_dark_mode, font_size=self.font_size)
        idx = self.tabs.addTab(ed, "\u65b0\u5efa.mabo")
        self.tabs.setCurrentWidget(ed)
        ed.setFocus()

    def open_from_list(self, item):
        path = os.path.join(self.workspace, item.text())
        # \u68c0\u67e5\u662f\u5426\u5df2\u7ecf\u6253\u5f00
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            if isinstance(w, MaboEditor) and w.file_path == path:
                self.tabs.setCurrentIndex(i)
                return
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            ed = MaboEditor(dark=self.is_dark_mode, font_size=self.font_size)
            ed.setPlainText(content)
            ed.file_path = path
            self.tabs.addTab(ed, item.text())
            self.tabs.setCurrentWidget(ed)
        except Exception as e:
            QMessageBox.warning(self, "\u9519\u8bef", str(e))

    def open_file(self):
        fp, _ = QFileDialog.getOpenFileName(self, "\u6253\u5f00", self.workspace, "Mabo (*.mabo);;Python (*.py);;All (*)")
        if fp:
            try:
                with open(fp, "r", encoding="utf-8") as f:
                    content = f.read()
                ed = MaboEditor(dark=self.is_dark_mode, font_size=self.font_size)
                ed.setPlainText(content)
                ed.file_path = fp
                self.tabs.addTab(ed, Path(fp).name)
                self.tabs.setCurrentWidget(ed)
            except Exception as e:
                QMessageBox.warning(self, "\u9519\u8bef", str(e))

    def save_file(self):
        ed = self.tabs.currentWidget()
        if not isinstance(ed, MaboEditor): return
        if ed.file_path:
            try:
                with open(ed.file_path, "w", encoding="utf-8") as f:
                    f.write(ed.toPlainText())
                self.refresh_file_list()
                self.statusBar().showMessage(f"\u5df2\u4fdd\u5b58\uff1a{ed.file_path}")
            except Exception as e:
                QMessageBox.warning(self, "\u4fdd\u5b58\u5931\u8d25", str(e))
        else:
            self.save_file_as()

    def save_file_as(self):
        ed = self.tabs.currentWidget()
        if not isinstance(ed, MaboEditor): return
        fp, _ = QFileDialog.getSaveFileName(self, "\u53e6\u5b58\u4e3a", self.workspace, "Mabo (*.mabo);;Python (*.py)")
        if fp:
            try:
                with open(fp, "w", encoding="utf-8") as f:
                    f.write(ed.toPlainText())
                ed.file_path = fp
                idx = self.tabs.indexOf(ed)
                self.tabs.setTabText(idx, Path(fp).name)
                self.refresh_file_list()
                self.statusBar().showMessage(f"\u5df2\u4fdd\u5b58\uff1a{fp}")
            except Exception as e:
                QMessageBox.warning(self, "\u4fdd\u5b58\u5931\u8d25", str(e))

    def format_code(self):
        ed = self.tabs.currentWidget()
        if not isinstance(ed, MaboEditor): return
        lines, out, ind = ed.toPlainText().splitlines(), [], 0
        for li in lines:
            s = li.strip()
            if not s:
                out.append("")
                continue
            if s.startswith("}"): ind = max(ind - 1, 0)
            out.append("    " * ind + s)
            if s.endswith("{"): ind += 1
        ed.setPlainText("\n".join(out))

    def run_code(self):
        # 如果有正在运行的线程，先安全停止
        if self.run_thread and self.run_thread.isRunning():
            self.run_thread.stop()
            # 不在 UI 线程 wait()，让线程自行退出后通过信号通知
            self.statusBar().showMessage("正在停止上一次运行...")

        ed = self.tabs.currentWidget()
        if not isinstance(ed, MaboEditor): return
        code = ed.toPlainText()
        if not code.strip():
            self.console.appendPlainText("[\u63d0\u793a] \u6ca1\u6709\u53ef\u8fd0\u884c\u7684\u4ee3\u7801")
            return

        self.console.clear()
        self.console.appendPlainText("\u2550\u2550\u2550 \u8fd0\u884c\u8f93\u51fa \u2550\u2550\u2550\n")

        source_lines = code.split('\n')
        self.run_thread = RunThread(code, source_lines)
        self.run_thread.output.connect(self._on_output)
        self.run_thread.error.connect(self._on_error)
        self.run_thread.finished_ok.connect(self._on_run_done)
        self.run_thread.start()
        self.statusBar().showMessage("\u8fd0\u884c\u4e2d...")

    def stop_run(self):
        if self.run_thread and self.run_thread.isRunning():
            self.run_thread.stop()
            self.statusBar().showMessage("\u6b63\u5728\u505c\u6b62...")

    def _on_output(self, text):
        self.bottom_tabs.setCurrentIndex(0)  # 切到运行输出 Tab
        self.console.appendPlainText(text)

    def _on_error(self, text):
        self.bottom_tabs.setCurrentIndex(0)  # 切到运行输出 Tab
        self.console.appendPlainText(f"\n[\u9519\u8bef]\n{text}")

    def _on_run_done(self):
        self.statusBar().showMessage("\u8fd0\u884c\u5b8c\u6210")

    def clear_console(self):
        self.console.clear()

    def closeEvent(self, event):
        self._save_config()
        super().closeEvent(event)

# ========== 启动 ==========
if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = MaboIDE()
    window.show()
    sys.exit(app.exec())
