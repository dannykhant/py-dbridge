package eqsql.dbridge.analysis.eqsql.expr.operator;

/**
 * Variable-arity operator for a list of SQL projection columns.
 * Used by ProjectionListNode to hold col1, col2, … inside a ProjectNode
 * without changing ProjectNode's own arity (which stays 2).
 */
public class ProjectionListOp extends Operator {
    public ProjectionListOp(int arity) {
        super("projList", OpType.ProjList, arity);
    }
}
