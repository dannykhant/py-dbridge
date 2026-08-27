package dbridge.eqsql;

import eqsql.dbridge.analysis.eqsql.expr.node.*;
import eqsql.dbridge.analysis.eqsql.expr.operator.*;

import java.util.ArrayList;
import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

public class SQLQueryParser {
    
    private List<Token> tokens;
    private int pos;
    private String dbType;
    
    private static class Token {
        String type;
        String value;
        Token(String type, String value) {
            this.type = type;
            this.value = value;
        }
    }
    
    public Node parse(String sql, String dbType) {
        this.dbType = dbType;
        tokenize(sql);
        pos = 0;
        
        try {
            return parseSelect();
        } catch (Exception e) {
            System.err.println("Failed to parse SQL: " + sql + " | Error: " + e.getMessage());
            return null;
        }
    }
    
    private void tokenize(String sql) {
        tokens = new ArrayList<>();
        // Tokenizer regex covering basic tokens
        String regex = "(?i)\\b(SELECT|DISTINCT|FROM|WHERE|GROUP\\s+BY|AND|OR)\\b" +
                "|(%(?:\\([a-zA-Z0-9_]+\\))?s)" + // postgres param
                "|\\?" + // positional param
                "|<=|>=|<>|<|>|=" +
                "|\\*" +
                "|,|\\(|\\)" +
                "|'[^']*'" + // string
                "|\\d+" + // int
                "|[a-zA-Z_][a-zA-Z0-9_]*"; // identifier
        
        Matcher m = Pattern.compile(regex).matcher(sql);
        while (m.find()) {
            String val = m.group();
            String upper = val.toUpperCase().replaceAll("\\s+", " "); // Normalize GROUP BY
            if (upper.equals("SELECT") || upper.equals("DISTINCT") || upper.equals("FROM") || 
                upper.equals("WHERE") || upper.equals("GROUP BY") || upper.equals("AND") || 
                upper.equals("OR")) {
                tokens.add(new Token("KEYWORD", upper));
            } else if (val.startsWith("%") || val.equals("?")) {
                tokens.add(new Token("PARAM", val));
            } else if (val.equals("<=") || val.equals(">=") || val.equals("<>") || 
                       val.equals("<") || val.equals(">") || val.equals("=")) {
                tokens.add(new Token("OP", val));
            } else if (val.equals(",") || val.equals("(") || val.equals(")") || val.equals("*")) {
                tokens.add(new Token("PUNCT", val));
            } else if (val.startsWith("'")) {
                tokens.add(new Token("STRING", val.substring(1, val.length() - 1)));
            } else if (val.matches("\\d+")) {
                tokens.add(new Token("INT", val));
            } else {
                tokens.add(new Token("IDENT", val));
            }
        }
    }
    
    private Token peek() {
        if (pos < tokens.size()) return tokens.get(pos);
        return null;
    }
    
    private Token next() {
        if (pos < tokens.size()) return tokens.get(pos++);
        return null;
    }
    
    private boolean matchKeyword(String keyword) {
        Token t = peek();
        if (t != null && t.type.equals("KEYWORD") && t.value.equals(keyword)) {
            next();
            return true;
        }
        return false;
    }
    
    private int paramIndex = 0;
    
    private Node parseSelect() {
        if (!matchKeyword("SELECT")) {
            return null; // Not a SELECT query
        }
        
        boolean distinct = matchKeyword("DISTINCT");
        
        List<Node> projCols = new ArrayList<>();
        do {
            projCols.add(parseProjectionCol());
        } while (peek() != null && peek().type.equals("PUNCT") && peek().value.equals(",") && next() != null);
        
        Node projectionNode;
        if (projCols.size() == 1) {
            projectionNode = projCols.get(0);
        } else {
            projectionNode = new ProjectionListNode(projCols.toArray(new Node[0]));
        }
        
        if (!matchKeyword("FROM")) {
            throw new RuntimeException("Expected FROM");
        }
        
        // Parse tables
        List<Node> tables = new ArrayList<>();
        do {
            Token t = next();
            if (t == null || !t.type.equals("IDENT")) {
                throw new RuntimeException("Expected table name");
            }
            tables.add(NodeFactory.constructFromOpType(OpType.ClassRef, t.value));
        } while (peek() != null && peek().type.equals("PUNCT") && peek().value.equals(",") && next() != null);
        Node fromNode = new CartesianProdNode(tables.toArray(new Node[0]));
        Node relNode = fromNode;
        if (matchKeyword("WHERE")) {
            Node condition = parseCondition();
            relNode = new SelectNode(relNode, condition);
        }
        
        ProjectNode projectNode = new ProjectNode(relNode, projectionNode, distinct);
        Node root = projectNode;
        
        if (matchKeyword("GROUP BY")) {
            Token t = next();
            if (t == null || !t.type.equals("IDENT")) {
                throw new RuntimeException("Expected column for GROUP BY");
            }
            VarNode groupByCol = new VarNode(t.value);
            root = new GroupByNode(projectNode, groupByCol);
        }
        
        return root;
    }
    
    private Node parseProjectionCol() {
        Token t = next();
        if (t == null) throw new RuntimeException("Expected projection column");
        
        if (t.type.equals("IDENT")) {
            String name = t.value;
            if (peek() != null && peek().type.equals("PUNCT") && peek().value.equals("(")) {
                // Function call like count(*) or max(id)
                next(); // consume '('
                
                Node arg;
                Token inner = next();
                if (inner.type.equals("PUNCT") && inner.value.equals("*")) {
                    arg = null; // Star
                } else if (inner.type.equals("IDENT")) {
                    arg = new VarNode(inner.value);
                } else {
                    throw new RuntimeException("Unexpected function argument");
                }
                
                Token closing = next();
                if (closing == null || !closing.type.equals("PUNCT") || !closing.value.equals(")")) {
                    throw new RuntimeException("Expected ')'");
                }
                
                if (name.equalsIgnoreCase("count") && arg == null) {
                    return new CountStarNode();
                } else {
                    return new VarNode(name + "(" + (arg != null ? arg.toString() : "*") + ")");
                }
            } else {
                return new VarNode(name);
            }
        }
        throw new RuntimeException("Unexpected projection token: " + t.value);
    }
    
    private Node parseCondition() {
        return parseOr();
    }
    
    private Node parseOr() {
        Node left = parseAnd();
        while (matchKeyword("OR")) {
            Node right = parseAnd();
            left = new OrNode(left, right);
        }
        return left;
    }
    
    private Node parseAnd() {
        Node left = parseComparison();
        while (matchKeyword("AND")) {
            Node right = parseComparison();
            left = new AndNode(left, right);
        }
        return left;
    }
    
    private Node parseComparison() {
        Node left = parseTerm();
        
        Token t = peek();
        if (t != null && t.type.equals("OP")) {
            next();
            String op = t.value;
            Node right = parseTerm();
            
            switch (op) {
                case "=": 
                    if ((left instanceof ParamNode) && !(right instanceof ParamNode)) {
                        return new EqNode(right, left);
                    }
                    return new EqNode(left, right);
                case "<>": return new NotEqNode(left, right);
                case "<": return new LtNode(left, right);
                case ">": return new GtNode(left, right);
                case "<=": return new LeNode(left, right);
                case ">=": return new GeNode(left, right);
                default: throw new RuntimeException("Unknown operator: " + op);
            }
        }
        
        return left;
    }
    
    private Node parseTerm() {
        Token t = next();
        if (t == null) throw new RuntimeException("Expected term");
        
        if (t.type.equals("IDENT")) {
            return new VarNode(t.value);
        } else if (t.type.equals("INT")) {
            return new IntConstNode(Integer.parseInt(t.value));
        } else if (t.type.equals("STRING")) {
            return new StringConstNode(t.value);
        } else if (t.type.equals("PARAM")) {
            String val = t.value;
            if (val.equals("?")) {
                return new SQLParamNode(paramIndex++, "?", null);
            } else if (val.equals("%s")) {
                return new SQLParamNode(paramIndex++, "%s", null);
            } else if (val.startsWith("%(") && val.endsWith(")s")) {
                String name = val.substring(2, val.length() - 2);
                return new SQLParamNode(paramIndex++, val, name);
            }
            return new SQLParamNode(paramIndex++, val, null);
        }
        
        throw new RuntimeException("Unexpected term: " + t.value);
    }
}
