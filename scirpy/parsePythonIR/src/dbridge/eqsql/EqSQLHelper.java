package dbridge.eqsql;

import eqsql.dbridge.analysis.eqsql.expr.node.*;
import eqsql.dbridge.analysis.eqsql.expr.operator.OpType;
import eqsql.dbridge.analysis.eqsql.trans.TransDriver;

import java.util.regex.Matcher;
import java.util.regex.Pattern;

public class EqSQLHelper {

    public static String optimizeQuery(String sql, String dbType) {
        try {
            String upperSql = sql.toUpperCase();
            
            // Consolidate safe refusals for unsupported SQL constructs
            if (upperSql.contains("ORDER BY") || 
                upperSql.contains("LIMIT") || 
                upperSql.contains("OFFSET") || 
                upperSql.contains("HAVING") || 
                upperSql.contains("JOIN") || 
                upperSql.matches(".*\\bOR\\b.*") || 
                upperSql.matches(".*\\bIN\\b.*") || 
                upperSql.matches(".*\\bANY\\b.*") || 
                upperSql.indexOf("SELECT") != upperSql.lastIndexOf("SELECT")) {
                return sql;
            }

            // Match SELECT queries with optional DISTINCT and WHERE clause (supports AND conditions)
            Pattern pattern = Pattern.compile("(?i)^\\s*SELECT\\s+(DISTINCT\\s+)?(.+?)\\s+FROM\\s+([a-zA-Z0-9_]+)\\s+WHERE\\s+(.+)$");
            Matcher matcher = pattern.matcher(sql);
            
            if (matcher.matches()) {
                boolean hasDistinct = matcher.group(1) != null;
                String projection = matcher.group(2).trim();
                String tableName = matcher.group(3).trim();
                String whereClause = matcher.group(4).trim();
                
                // Match parameterized condition
                Matcher condMatcher = Pattern.compile("(?i)\\b([a-zA-Z0-9_.]+)\\s*=\\s*(\\?|%s|%\\([a-zA-Z0-9_]+\\)s)").matcher(whereClause);
                
                if (!condMatcher.find()) {
                    return sql;
                }
                
                String batchWhereCol = condMatcher.group(1);
                String placeholder = condMatcher.group(2);

                String lowerProj = projection.toLowerCase();
                boolean hasAggregate = false;
                String[] projParts = lowerProj.split(",");
                for (String part : projParts) {
                    part = part.trim();
                    // Refuse complex expressions with operators like count(a) + 1
                    if (part.contains("+") || part.contains("-") || part.contains("/") || (part.contains("*") && !part.equals("count(*)"))) {
                        return sql;
                    }
                    if (part.matches("^(count|sum|avg|min|max)\\s*\\(.*\\)$")) {
                        hasAggregate = true;
                    } else if (part.contains("count(") || part.contains("sum(") || part.contains("avg(") || part.contains("min(") || part.contains("max(")) {
                        // Refuse unrecognized aggregate expression
                        return sql;
                    }
                }
                
                boolean isGroupBy = hasAggregate;
                
                String batchCond = "";
                if ("postgres".equalsIgnoreCase(dbType)) {
                    if (placeholder.startsWith("%(") && placeholder.endsWith(")s")) {
                        batchCond = "= ANY(" + placeholder + ")";
                    } else {
                        batchCond = "= ANY(%s)";
                    }
                } else if ("sqlite".equalsIgnoreCase(dbType)) {
                    batchCond = "IN ({})";
                } else {
                    batchCond = "IN (?)";
                }

                String selectPrefix = hasDistinct ? "SELECT DISTINCT " : "SELECT ";
                String newWhereClause = whereClause.replaceAll("=\\s*" + Pattern.quote(placeholder), batchCond);

                if (isGroupBy) {
                    return selectPrefix + batchWhereCol + ", " + projection + " FROM " + tableName + " WHERE " + newWhereClause + " GROUP BY " + batchWhereCol;
                } else {
                    return selectPrefix + batchWhereCol + ", " + projection + " FROM " + tableName + " WHERE " + newWhereClause;
                }
            }
        } catch (Exception e) {
            System.err.println("EqSQLHelper optimization error:");
            e.printStackTrace(System.err);
        }
        
        return sql;
    }
}
