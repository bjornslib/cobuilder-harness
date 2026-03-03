"""Custom recursive-descent DOT parser for Attractor pipeline files.

Implements a complete lexer + parser without any external graphviz dependency.
The parser produces typed ``Graph``, ``Node``, and ``Edge`` objects ready for
use by the execution engine.

Design goals (from SD-PIPELINE-ENGINE-001 Section 4.1 / community survey):
- Zero external dependencies beyond Python stdlib
- ``ParseError`` with line number and source snippet for actionable diagnostics
- Preserves all attribute values verbatim (including multiline quoted strings)
- Handles the full DOT subset used by Attractor pipelines:
    - ``digraph`` declarations with optional quoted names
    - Graph-level attribute blocks: ``graph [...]``
    - Default attribute blocks: ``node [...]``, ``edge [...]``
    - Node definitions: ``id [attr_list]`` or bare ``id;``
    - Edge definitions: ``src -> dst [attr_list]``
    - Line comments (``// ...``) and block comments (``/* ... */``)
    - Quoted string values with ``\\``, ``\"``, ``\n``, ``\l``, ``\r`` escapes
    - Unquoted identifiers and numeric values
- Subgraph blocks are silently skipped (not used by current Attractor schemas)

Grammar (simplified):
    file         := 'digraph' name? '{' stmt* '}'
    stmt         := graph_stmt | default_stmt | node_stmt | edge_stmt | ';'
    graph_stmt   := 'graph' attr_list
    default_stmt := ('node' | 'edge') attr_list
    node_stmt    := id attr_list?
    edge_stmt    := id ('->' id)+ attr_list?
    attr_list    := '[' attr_pair* ']'
    attr_pair    := key '=' value (';' | ',')?
    name         := STRING | IDENT
    id           := STRING | IDENT | NUMBER

Token types:
    KEYWORD    digraph, graph, subgraph, node, edge
    IDENT      bare identifier (letters, digits, underscores, hyphens)
    STRING     double-quoted string (escape sequences decoded)
    NUMBER     integer or float literal
    ARROW      ->
    LBRACE     {
    RBRACE     }
    LBRACKET   [
    RBRACKET   ]
    EQUALS     =
    SEMI       ;
    COMMA      ,
    EOF        end of input
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Any

from cobuilder.engine.graph import Edge, Graph, Node


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class ParseError(Exception):
    """Raised when the DOT source cannot be parsed.

    Attributes:
        message:  Human-readable description of the problem.
        line:     1-based line number in the source where the error occurred.
                  ``0`` means the line could not be determined.
        column:   1-based column number in the source where the error occurred.
                  ``0`` means the column could not be determined.
        snippet:  The offending source fragment (up to 80 characters).
    """

    def __init__(self, message: str, line: int = 0, snippet: str = "", column: int = 0) -> None:
        self.message = message
        self.line = line
        self.column = column
        self.snippet = snippet
        loc = f" (line {line}, col {column})" if line else ""
        snip = f": {snippet!r}" if snippet else ""
        super().__init__(f"{message}{loc}{snip}")


# ---------------------------------------------------------------------------
# Token types and the Token dataclass
# ---------------------------------------------------------------------------

class TT(Enum):  # Token Type
    """Enumeration of all token types produced by the lexer."""
    KEYWORD    = auto()
    IDENT      = auto()
    STRING     = auto()
    NUMBER     = auto()
    ARROW      = auto()
    LBRACE     = auto()
    RBRACE     = auto()
    LBRACKET   = auto()
    RBRACKET   = auto()
    EQUALS     = auto()
    SEMI       = auto()
    COMMA      = auto()
    EOF        = auto()


# Keywords that get their own TT.KEYWORD token (case-sensitive in DOT)
_KEYWORDS: frozenset[str] = frozenset(
    {"digraph", "graph", "subgraph", "node", "edge", "strict"}
)


@dataclass(frozen=True)
class Token:
    """A single lexical token with its type, value, and source location."""
    type: TT
    value: str
    line: int   # 1-based line in the source file


# ---------------------------------------------------------------------------
# Lexer
# ---------------------------------------------------------------------------

class _Lexer:
    """Converts a DOT source string into a flat list of tokens.

    Handles:
    - Line comments  ``// ...`` and block comments ``/* ... */``
    - Double-quoted strings with escape sequences
    - Identifiers (letters, digits, underscores; also hyphens mid-identifier)
    - Numeric literals (integer and float)
    - The two-character operator ``->``
    - All single-character punctuation tokens
    """

    def __init__(self, source: str) -> None:
        self._src = source
        self._pos = 0
        self._line = 1
        self._tokens: list[Token] = []

    def tokenize(self) -> list[Token]:
        """Tokenize the full source and return the token list."""
        while self._pos < len(self._src):
            self._skip_whitespace_and_comments()
            if self._pos >= len(self._src):
                break
            ch = self._src[self._pos]
            tok_line = self._line

            if ch == '"':
                value = self._read_string()
                self._tokens.append(Token(TT.STRING, value, tok_line))
            elif ch == '-' and self._peek(1) == '>':
                self._pos += 2
                self._tokens.append(Token(TT.ARROW, "->", tok_line))
            elif ch == '{':
                self._pos += 1
                self._tokens.append(Token(TT.LBRACE, "{", tok_line))
            elif ch == '}':
                self._pos += 1
                self._tokens.append(Token(TT.RBRACE, "}", tok_line))
            elif ch == '[':
                self._pos += 1
                self._tokens.append(Token(TT.LBRACKET, "[", tok_line))
            elif ch == ']':
                self._pos += 1
                self._tokens.append(Token(TT.RBRACKET, "]", tok_line))
            elif ch == '=':
                self._pos += 1
                self._tokens.append(Token(TT.EQUALS, "=", tok_line))
            elif ch == ';':
                self._pos += 1
                self._tokens.append(Token(TT.SEMI, ";", tok_line))
            elif ch == ',':
                self._pos += 1
                self._tokens.append(Token(TT.COMMA, ",", tok_line))
            elif ch.isdigit() or (ch == '-' and self._peek(1, '').isdigit()):
                value = self._read_number()
                self._tokens.append(Token(TT.NUMBER, value, tok_line))
            elif self._is_ident_start(ch):
                value = self._read_ident()
                tt = TT.KEYWORD if value in _KEYWORDS else TT.IDENT
                self._tokens.append(Token(tt, value, tok_line))
            else:
                # Unknown character — skip with a warning (tolerant mode)
                self._pos += 1

        self._tokens.append(Token(TT.EOF, "", self._line))
        return self._tokens

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _peek(self, offset: int = 1, default: str = "") -> str:
        idx = self._pos + offset
        return self._src[idx] if idx < len(self._src) else default

    def _skip_whitespace_and_comments(self) -> None:
        while self._pos < len(self._src):
            ch = self._src[self._pos]
            if ch in ' \t\r':
                self._pos += 1
            elif ch == '\n':
                self._pos += 1
                self._line += 1
            elif ch == '/' and self._peek() == '/':
                # Line comment: skip to end of line
                while self._pos < len(self._src) and self._src[self._pos] != '\n':
                    self._pos += 1
            elif ch == '/' and self._peek() == '*':
                # Block comment: skip until */
                self._pos += 2
                while self._pos < len(self._src) - 1:
                    if self._src[self._pos] == '\n':
                        self._line += 1
                    if self._src[self._pos] == '*' and self._src[self._pos + 1] == '/':
                        self._pos += 2
                        break
                    self._pos += 1
            elif ch == '#':
                # C-preprocessor-style comment (DOT supports this too)
                while self._pos < len(self._src) and self._src[self._pos] != '\n':
                    self._pos += 1
            else:
                break

    def _read_string(self) -> str:
        """Read a double-quoted string, decoding standard escape sequences."""
        self._pos += 1  # skip opening "
        chars: list[str] = []
        while self._pos < len(self._src):
            ch = self._src[self._pos]
            if ch == '\\' and self._pos + 1 < len(self._src):
                nxt = self._src[self._pos + 1]
                if nxt == '"':
                    chars.append('"')
                elif nxt == '\\':
                    chars.append('\\')
                elif nxt == 'n':
                    chars.append('\n')
                elif nxt == 'l':
                    # DOT left-align marker — preserve as \l so callers can
                    # strip it if they want; we do not silently discard it.
                    chars.append('\\l')
                elif nxt == 'r':
                    chars.append('\\r')
                else:
                    # Unknown escape — pass through both characters
                    chars.append('\\')
                    chars.append(nxt)
                self._pos += 2
            elif ch == '"':
                self._pos += 1  # skip closing "
                break
            elif ch == '\n':
                # DOT allows newlines inside quoted strings
                chars.append('\n')
                self._pos += 1
                self._line += 1
            else:
                chars.append(ch)
                self._pos += 1
        return ''.join(chars)

    def _read_number(self) -> str:
        """Read an integer or float literal."""
        start = self._pos
        if self._src[self._pos] == '-':
            self._pos += 1
        while self._pos < len(self._src) and (
            self._src[self._pos].isdigit() or self._src[self._pos] == '.'
        ):
            self._pos += 1
        return self._src[start:self._pos]

    def _read_ident(self) -> str:
        """Read an identifier (letters, digits, underscores, hyphens)."""
        start = self._pos
        while self._pos < len(self._src) and self._is_ident_body(self._src[self._pos]):
            self._pos += 1
        return self._src[start:self._pos]

    @staticmethod
    def _is_ident_start(ch: str) -> bool:
        return ch.isalpha() or ch == '_'

    @staticmethod
    def _is_ident_body(ch: str) -> bool:
        return ch.isalnum() or ch in ('_', '-', '.')


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

class _Parser:
    """Recursive-descent parser that builds ``Graph`` / ``Node`` / ``Edge`` objects.

    Consumes the flat token list produced by ``_Lexer`` and applies the
    DOT grammar to produce a typed ``Graph``.
    """

    def __init__(self, tokens: list[Token], source_lines: list[str]) -> None:
        self._tokens = tokens
        self._pos = 0
        self._source_lines = source_lines

        # Accumulated output
        self._graph_name: str = ""
        self._graph_attrs: dict[str, Any] = {}
        self._default_node_attrs: dict[str, Any] = {}
        self._default_edge_attrs: dict[str, Any] = {}
        self._nodes: dict[str, Node] = {}   # preserves insertion order (Python 3.7+)
        self._edges: list[Edge] = []
        self._seen_edges: set[tuple[str, str, str]] = set()  # dedup key

    # ------------------------------------------------------------------
    # Token navigation
    # ------------------------------------------------------------------

    def _current(self) -> Token:
        return self._tokens[self._pos]

    def _peek(self, offset: int = 1) -> Token:
        idx = self._pos + offset
        return self._tokens[idx] if idx < len(self._tokens) else self._tokens[-1]

    def _advance(self) -> Token:
        tok = self._tokens[self._pos]
        if self._pos < len(self._tokens) - 1:
            self._pos += 1
        return tok

    def _expect(self, tt: TT) -> Token:
        tok = self._current()
        if tok.type != tt:
            self._raise(
                f"Expected {tt.name} but got {tok.type.name} ({tok.value!r})",
                tok,
            )
        return self._advance()

    def _match(self, *types: TT) -> bool:
        return self._current().type in types

    def _match_value(self, value: str) -> bool:
        return self._current().value == value

    def _raise(self, message: str, tok: Token | None = None) -> None:
        line = tok.line if tok else 0
        snippet = ""
        column = 0
        if line and 1 <= line <= len(self._source_lines):
            raw_line = self._source_lines[line - 1]
            snippet = raw_line.strip()[:80]
            if tok and tok.value:
                idx = raw_line.find(tok.value)
                if idx >= 0:
                    column = idx + 1  # 1-based
        raise ParseError(message, line=line, snippet=snippet, column=column)

    # ------------------------------------------------------------------
    # Top-level parse
    # ------------------------------------------------------------------

    def parse(self) -> Graph:
        """Parse all tokens and return a ``Graph`` instance."""
        self._parse_graph()
        return Graph(
            name=self._graph_name,
            attrs=self._graph_attrs,
            nodes=self._nodes,
            edges=self._edges,
        )

    def _parse_graph(self) -> None:
        """Parse: ('strict')? 'digraph' name? '{' stmt* '}'"""
        # Optional 'strict' keyword
        if self._match(TT.KEYWORD) and self._match_value("strict"):
            self._advance()

        # Require 'digraph'
        tok = self._current()
        if not (self._match(TT.KEYWORD) and self._match_value("digraph")):
            self._raise(
                f"Expected 'digraph' at start of file, got {tok.value!r}", tok
            )
        self._advance()

        # Optional graph name
        if self._match(TT.IDENT, TT.STRING, TT.NUMBER):
            self._graph_name = self._advance().value

        self._expect(TT.LBRACE)
        self._parse_stmt_list()
        self._expect(TT.RBRACE)

    def _parse_stmt_list(self) -> None:
        """Parse zero or more statements inside the graph body."""
        while not self._match(TT.RBRACE, TT.EOF):
            # Skip bare semicolons
            if self._match(TT.SEMI):
                self._advance()
                continue
            self._parse_stmt()

    def _parse_stmt(self) -> None:
        """Dispatch a single statement to its handler."""
        tok = self._current()

        # graph [...] — graph-level attributes
        if self._match(TT.KEYWORD) and self._match_value("graph"):
            self._advance()
            if self._match(TT.LBRACKET):
                attrs = self._parse_attr_list()
                self._graph_attrs.update(attrs)
            return

        # node [...] — default node attributes
        if self._match(TT.KEYWORD) and self._match_value("node"):
            self._advance()
            if self._match(TT.LBRACKET):
                attrs = self._parse_attr_list()
                self._default_node_attrs.update(attrs)
            return

        # edge [...] — default edge attributes
        if self._match(TT.KEYWORD) and self._match_value("edge"):
            self._advance()
            if self._match(TT.LBRACKET):
                attrs = self._parse_attr_list()
                self._default_edge_attrs.update(attrs)
            return

        # subgraph — skip the entire block
        if self._match(TT.KEYWORD) and self._match_value("subgraph"):
            self._skip_subgraph()
            return

        # Node or edge statement: must start with an identifier / string / number
        if self._match(TT.IDENT, TT.STRING, TT.NUMBER):
            self._parse_node_or_edge_stmt()
            return

        # Unknown token — skip to recover
        self._advance()

    def _skip_subgraph(self) -> None:
        """Consume a subgraph block without producing any nodes or edges."""
        self._advance()  # 'subgraph'
        # Optional subgraph name
        if self._match(TT.IDENT, TT.STRING):
            self._advance()
        if self._match(TT.LBRACE):
            self._advance()
            depth = 1
            while not self._match(TT.EOF) and depth > 0:
                if self._match(TT.LBRACE):
                    depth += 1
                elif self._match(TT.RBRACE):
                    depth -= 1
                self._advance()

    def _parse_node_or_edge_stmt(self) -> None:
        """Parse either a node definition or an edge chain.

        Both start with an identifier.  We look ahead for '->' to decide.

        Edge chains: ``a -> b -> c [attrs]``
        Node stmt:   ``a [attrs]`` or just ``a``
        """
        first_id = self._advance().value  # consume first identifier

        if self._match(TT.ARROW):
            # Edge statement
            targets: list[str] = [first_id]
            while self._match(TT.ARROW):
                self._advance()  # consume '->'
                if not self._match(TT.IDENT, TT.STRING, TT.NUMBER):
                    self._raise(
                        "Expected node identifier after '->'", self._current()
                    )
                targets.append(self._advance().value)

            attrs: dict[str, Any] = {}
            if self._match(TT.LBRACKET):
                attrs = self._parse_attr_list()

            # Materialise implied nodes (nodes referenced in edges but not
            # yet given an explicit node definition inherit default attrs)
            for nid in targets:
                if nid not in self._nodes:
                    self._add_node(nid, {})

            # Create one edge per consecutive pair in the chain
            for i in range(len(targets) - 1):
                src, dst = targets[i], targets[i + 1]
                merged = dict(self._default_edge_attrs)
                merged.update(attrs)
                self._add_edge(src, dst, merged)

        else:
            # Node statement
            attrs = {}
            if self._match(TT.LBRACKET):
                attrs = self._parse_attr_list()
            self._add_node(first_id, attrs)

        # Consume optional trailing semicolon
        if self._match(TT.SEMI):
            self._advance()

    # ------------------------------------------------------------------
    # Attribute list parser
    # ------------------------------------------------------------------

    def _parse_attr_list(self) -> dict[str, Any]:
        """Parse ``[ key=value (, | ;)? ... ]`` and return a dict."""
        self._expect(TT.LBRACKET)
        attrs: dict[str, Any] = {}
        while not self._match(TT.RBRACKET, TT.EOF):
            # Skip extra commas / semicolons between pairs
            while self._match(TT.COMMA, TT.SEMI):
                self._advance()
            if self._match(TT.RBRACKET, TT.EOF):
                break

            # Key
            key_tok = self._current()
            if not self._match(TT.IDENT, TT.STRING, TT.NUMBER, TT.KEYWORD):
                self._raise(
                    f"Expected attribute key, got {key_tok.value!r}", key_tok
                )
            key = self._advance().value

            if not self._match(TT.EQUALS):
                # Bare attribute without a value (e.g. ``style``) — skip
                continue
            self._advance()  # consume '='

            # Value
            val_tok = self._current()
            if self._match(TT.STRING, TT.IDENT, TT.NUMBER, TT.KEYWORD):
                value: Any = self._advance().value
            else:
                self._raise(
                    f"Expected attribute value after '=', got {val_tok.value!r}",
                    val_tok,
                )
                value = ""  # unreachable, for type checkers

            attrs[key] = value

            # Optional trailing comma or semicolon after a pair
            while self._match(TT.COMMA, TT.SEMI):
                self._advance()

        self._expect(TT.RBRACKET)
        return attrs

    # ------------------------------------------------------------------
    # Node / edge creation helpers
    # ------------------------------------------------------------------

    def _add_node(self, node_id: str, raw_attrs: dict[str, Any]) -> None:
        """Merge default node attrs with raw_attrs and upsert node into graph."""
        merged = dict(self._default_node_attrs)
        merged.update(raw_attrs)

        # Normalise shape — DOT uses 'shape' attribute
        shape = merged.get("shape", "box")

        # Normalise label — strip DOT alignment markers for cleaner display
        label = merged.get("label", node_id)
        label = self._clean_label(label)

        if node_id in self._nodes:
            # Re-declaration: merge new attrs into existing node
            existing = self._nodes[node_id]
            existing.attrs.update(merged)
            # Also update shape/label if the re-declaration provides them
            if "shape" in raw_attrs:
                object.__setattr__(existing, "shape", shape)  # dataclass is not frozen
            if "label" in raw_attrs:
                object.__setattr__(existing, "label", label)
        else:
            self._nodes[node_id] = Node(
                id=node_id,
                shape=shape,
                label=label,
                attrs=merged,
            )

    def _add_edge(
        self, source: str, target: str, attrs: dict[str, Any]
    ) -> None:
        """Create an Edge from source → target with the given attributes.

        Duplicate edges (same source, target, and label) are deduplicated
        to match the behaviour of graphviz's ``dotty`` parser.
        """
        label = attrs.get("label", "")
        condition = attrs.get("condition", "")
        dedup_key = (source, target, label)

        if dedup_key in self._seen_edges:
            # Already recorded — update attrs on existing edge instead
            for edge in self._edges:
                if edge.source == source and edge.target == target and edge.label == label:
                    edge.attrs.update(attrs)
                    return
        self._seen_edges.add(dedup_key)

        weight: float | None = None
        raw_weight = attrs.get("weight")
        if raw_weight is not None:
            try:
                weight = float(raw_weight)
            except (ValueError, TypeError):
                weight = None

        loop_restart_raw = attrs.get("loop_restart", "false")
        loop_restart = str(loop_restart_raw).lower() == "true"

        self._edges.append(
            Edge(
                source=source,
                target=target,
                label=label,
                condition=condition,
                weight=weight,
                loop_restart=loop_restart,
                attrs=attrs,
            )
        )

    @staticmethod
    def _clean_label(label: str) -> str:
        """Strip DOT alignment markers (``\\l``, ``\\r``, ``\\n``) from labels."""
        return label.replace("\\l", "\n").replace("\\r", "\n")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class DotParser:
    """High-level facade for the recursive-descent DOT parser.

    Usage::

        parser = DotParser()
        graph = parser.parse_file("/path/to/pipeline.dot")
        # or:
        graph = parser.parse_string(dot_source)

    Thread-safe: each call to ``parse_file`` / ``parse_string`` creates a
    fresh internal ``_Lexer`` and ``_Parser`` instance.
    """

    def parse_file(self, path: str | Path) -> Graph:
        """Parse a DOT file from disk and return a typed ``Graph``.

        Args:
            path: Absolute or relative path to the ``.dot`` file.

        Returns:
            Parsed ``Graph`` with all nodes and edges populated.

        Raises:
            ParseError: If the DOT source is malformed.
            FileNotFoundError: If *path* does not exist.
            IOError: If the file cannot be read.
        """
        content = Path(path).read_text(encoding="utf-8")
        return self.parse_string(content)

    def parse_string(self, source: str) -> Graph:
        """Parse a DOT source string and return a typed ``Graph``.

        Args:
            source: Full DOT file content as a string.

        Returns:
            Parsed ``Graph`` with all nodes and edges populated.

        Raises:
            ParseError: If the DOT source is malformed.
        """
        source_lines = source.splitlines()
        tokens = _Lexer(source).tokenize()
        parser = _Parser(tokens, source_lines)
        return parser.parse()


# ---------------------------------------------------------------------------
# Module-level convenience functions
# ---------------------------------------------------------------------------

def parse_dot_file(path: str | Path) -> Graph:
    """Parse a DOT file from disk.  Convenience wrapper around ``DotParser``."""
    return DotParser().parse_file(path)


def parse_dot_string(source: str) -> Graph:
    """Parse a DOT source string.  Convenience wrapper around ``DotParser``."""
    return DotParser().parse_string(source)
