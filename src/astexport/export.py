import ast
import json


def export_json(tree, pretty_print=False):
    assert(isinstance(tree, ast.AST))
    return json.dumps(
        export_dict(tree),
        indent=4 if pretty_print else None,
        sort_keys=True,
        separators=(",", ": ") if pretty_print else (",", ":")
    )


def export_dict(tree):
    assert(isinstance(tree, ast.AST))
    return DictExportVisitor().visit(tree)


class DictExportVisitor:
    ast_type_field = "ast_type"

    def visit(self, node):
        node_type = node.__class__.__name__
        meth = getattr(self, "visit_" + node_type, self.default_visit)
        return meth(node)

    def default_visit(self, node):
        node_type = node.__class__.__name__
        # Add node type
        args = {
            self.ast_type_field: node_type
        }
        # Visit fields
        for field in node._fields:
            assert field != self.ast_type_field
            meth = getattr(
                self, "visit_field_" + node_type + "_" + field,
                self.default_visit_field
            )
            args[field] = meth(getattr(node, field))
        # Visit attributes
        for attr in node._attributes:
            assert attr != self.ast_type_field
            meth = getattr(
                self, "visit_attribute_" + node_type + "_" + attr,
                self.default_visit_field
            )
            # Use None as default when lineno/col_offset are not set
            args[attr] = meth(getattr(node, attr, None))
        return args

    def default_visit_field(self, val):
        if isinstance(val, ast.AST):
            return self.visit(val)
        elif isinstance(val, list) or isinstance(val, tuple):
            return [self.visit(x) for x in val]
        else:
            return val

    # Special visitors

    def visit_str(self, val):
        return str(val)

    def visit_Bytes(self, val):
        return str(val.s)

    def visit_NoneType(self, val):
        return None

    def visit_field_NameConstant_value(self, val):
        return str(val)

    def visit_field_Num_n(self, val):
        if isinstance(val, int):
            return {
                self.ast_type_field: "int",
                "n": val,
                # JavaScript integers are limited to 2**53 - 1 bits,
                # so we add a string representation of the integer
                "n_str": str(val),
            }
        elif isinstance(val, float):
            return {
                self.ast_type_field: "float",
                "n": val
            }
        elif isinstance(val, complex):
            return {
                self.ast_type_field: "complex",
                "n": val.real,
                "i": val.imag
            }

    def visit_Constant(self, node):
        val = node.value
        lineno = getattr(node, "lineno", None)
        col_offset = getattr(node, "col_offset", None)
        if isinstance(val, bool) or val is None:
            return {
                self.ast_type_field: "NameConstant",
                "value": str(val),
                "lineno": lineno,
                "col_offset": col_offset,
            }
        elif isinstance(val, (int, float, complex)):
            if isinstance(val, int):
                n_dict = {
                    self.ast_type_field: "int",
                    "n": val,
                    "n_str": str(val),
                }
            elif isinstance(val, float):
                n_dict = {
                    self.ast_type_field: "float",
                    "n": val
                }
            else:
                n_dict = {
                    self.ast_type_field: "complex",
                    "n": val.real,
                    "i": val.imag
                }
            return {
                self.ast_type_field: "Num",
                "n": n_dict,
                "lineno": lineno,
                "col_offset": col_offset,
            }
        elif isinstance(val, str):
            return {
                self.ast_type_field: "Str",
                "s": val,
                "lineno": lineno,
                "col_offset": col_offset,
            }
        elif isinstance(val, bytes):
            return {
                self.ast_type_field: "Bytes",
                "s": str(val),
                "lineno": lineno,
                "col_offset": col_offset,
            }
        return self.default_visit(node)
