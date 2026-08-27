package dbridge;

import ir.IStmt;
import ir.IExpr;
import ir.Stmt.AssignStmt;
import ir.Stmt.AssignmentStmtSoot;
import ir.Stmt.CallExprStmt;
import ir.expr.*;
import soot.Body;
import soot.Unit;
import soot.Value;
import soot.ValueBox;
import soot.jimple.Stmt;
import soot.jimple.toolkits.annotation.logic.Loop;
import soot.toolkits.graph.BriefUnitGraph;

import java.util.*;

public class DbridgePDG {

    public static class Dep {
        public int src;
        public int tgt;
        public String var;
        public String type;

        public Dep(int src, int tgt, String var, String type) {
            this.src = src;
            this.tgt = tgt;
            this.var = (var != null) ? var : "";
            this.type = (type != null) ? type : "";
        }

        @Override
        public boolean equals(Object o) {
            if (this == o) return true;
            if (!(o instanceof Dep)) return false;
            Dep dep = (Dep) o;
            return src == dep.src && tgt == dep.tgt &&
                   Objects.equals(var, dep.var) &&
                   Objects.equals(type, dep.type);
        }

        @Override
        public int hashCode() {
            return Objects.hash(src, tgt, var, type);
        }

        @Override
        public String toString() {
            return "Dep{" + src + " -> " + tgt + ", var='" + var + "', type='" + type + "'}";
        }
    }

    public static class StmtUnitInfo {
        public Unit unit;
        public int lineno;
        public Set<String> defs = new LinkedHashSet<>();
        public Set<String> uses = new LinkedHashSet<>();
        public String methodName = null;
        public boolean isExecute = false;
        public boolean isFetch = false;

        public StmtUnitInfo(Unit unit) {
            this.unit = unit;
            this.lineno = (unit instanceof IStmt) ? ((IStmt) unit).getLineno() : -1;
            extractDefsAndUses();
            classifyCall();
        }

        private void extractDefsAndUses() {
            for (ValueBox vb : unit.getDefBoxes()) {
                String varName = getVarName(vb.getValue());
                if (varName != null && !varName.isEmpty()) {
                    defs.add(varName);
                }
            }
            if (unit instanceof AssignmentStmtSoot) {
                AssignmentStmtSoot as = (AssignmentStmtSoot) unit;
                String varName = getVarName(as.getLeftOp());
                if (varName != null && !varName.isEmpty()) {
                    defs.add(varName);
                }
                if (as.getAssignStmt() != null) {
                    for (IExpr target : as.getAssignStmt().getTargets()) {
                        if (target instanceof Name) {
                            defs.add(((Name) target).getName());
                        } else if (target != null) {
                            String s = target.toString();
                            if (isValidVarName(s)) defs.add(s);
                        }
                    }
                    collectUsesFromExpr(as.getAssignStmt().getRHS(), uses);
                }
            }
            if (unit instanceof AssignStmt) {
                AssignStmt as = (AssignStmt) unit;
                for (IExpr target : as.getTargets()) {
                    if (target instanceof Name) {
                        defs.add(((Name) target).getName());
                    } else if (target != null) {
                        String s = target.toString();
                        if (isValidVarName(s)) defs.add(s);
                    }
                }
                collectUsesFromExpr(as.getRHS(), uses);
            }
            if (unit instanceof CallExprStmt) {
                CallExprStmt cs = (CallExprStmt) unit;
                collectUsesFromExpr(cs.getCallExpr(), uses);
            }

            for (ValueBox vb : unit.getUseBoxes()) {
                String varName = getVarName(vb.getValue());
                if (varName != null && !varName.isEmpty()) {
                    uses.add(varName);
                }
            }
        }

        private void classifyCall() {
            this.methodName = getCalledMethodName(unit);
            if (methodName != null) {
                if (methodName.equals("execute") || methodName.equals("executemany")) {
                    isExecute = true;
                } else if (methodName.equals("fetchone") || methodName.equals("fetchall") || methodName.equals("fetchmany")) {
                    isFetch = true;
                }
            }
        }
    }

    public static void collectUsesFromExpr(IExpr expr, Set<String> outUses) {
        if (expr == null) return;
        if (expr instanceof Name) {
            String n = ((Name) expr).getName();
            if (isValidVarName(n)) outUses.add(n);
        } else if (expr instanceof NameLocal) {
            String n = ((NameLocal) expr).getName();
            if (isValidVarName(n)) outUses.add(n);
        } else if (expr instanceof Call) {
            Call c = (Call) expr;
            collectUsesFromExpr(c.getFunc(), outUses);
            if (c.getArgs() != null) {
                for (IExpr arg : c.getArgs()) {
                    collectUsesFromExpr(arg, outUses);
                }
            }
            if (c.getKeywords() != null) {
                for (Object kw : c.getKeywords()) {
                    if (kw instanceof ir.internalast.Keyword) {
                        collectUsesFromExpr((IExpr) ((ir.internalast.Keyword) kw).getValue(), outUses);
                    }
                }
            }
        } else if (expr instanceof ListComp) {
            ListComp lc = (ListComp) expr;
            if (lc.getElts() != null) {
                for (IExpr elt : lc.getElts()) {
                    collectUsesFromExpr(elt, outUses);
                }
            }
        } else if (expr instanceof Subscript) {
            Subscript sub = (Subscript) expr;
            collectUsesFromExpr(sub.getValue(), outUses);
            if (sub.getSlice() != null) {
                ir.internalast.Slice sl = sub.getSlice();
                collectUsesFromExpr(sl.getLower(), outUses);
                collectUsesFromExpr(sl.getUpper(), outUses);
                collectUsesFromExpr(sl.getStep(), outUses);
                collectUsesFromExpr(sl.getValue(), outUses);
                collectUsesFromExpr(sl.getIndex(), outUses);
            }
        } else if (expr instanceof Attribute) {
            Attribute attr = (Attribute) expr;
            collectUsesFromExpr(attr.getValue(), outUses);
        } else if (expr instanceof BinOp) {
            BinOp b = (BinOp) expr;
            collectUsesFromExpr(b.getLeft(), outUses);
            collectUsesFromExpr(b.getRight(), outUses);
        } else if (expr instanceof UnaryOp) {
            UnaryOp u = (UnaryOp) expr;
            collectUsesFromExpr(u.getOperand(), outUses);
        } else if (expr instanceof BoolOp) {
            BoolOp bo = (BoolOp) expr;
            if (bo.getValues() != null) {
                for (Object v : bo.getValues()) {
                    if (v instanceof IExpr) {
                        collectUsesFromExpr((IExpr) v, outUses);
                    }
                }
            }
        } else if (expr instanceof Compare) {
            Compare cmp = (Compare) expr;
            collectUsesFromExpr(cmp.getLeft(), outUses);
            if (cmp.getComparators() != null) {
                for (IExpr v : cmp.getComparators()) {
                    collectUsesFromExpr(v, outUses);
                }
            }
        } else if (expr instanceof Dict) {
            Dict d = (Dict) expr;
            if (d.getKeys() != null) {
                for (IExpr k : d.getKeys()) collectUsesFromExpr(k, outUses);
            }
            if (d.getValue() != null) {
                for (IExpr v : d.getValue()) collectUsesFromExpr(v, outUses);
            }
        }
    }

    public static String getVarName(Value val) {
        if (val == null) return null;
        if (val instanceof soot.jimple.Constant) return null;
        if (val instanceof ir.expr.Num || val instanceof ir.expr.Str) return null;
        if (val instanceof soot.Local) return ((soot.Local) val).getName();
        if (val instanceof ir.expr.Name) return ((ir.expr.Name) val).getName();
        String s = val.toString();
        if (s.startsWith("\"") || s.startsWith("'")) return null;
        if (!isValidVarName(s)) return null;
        return s;
    }

    private static boolean isValidVarName(String s) {
        if (s == null || s.isEmpty()) return false;
        try {
            Double.parseDouble(s);
            return false;
        } catch (NumberFormatException ignored) {}
        return true;
    }

    public static String getCalledMethodName(Unit u) {
        if (u == null) return null;
        if (u instanceof Stmt && ((Stmt) u).containsInvokeExpr()) {
            try {
                return ((Stmt) u).getInvokeExpr().getMethod().getName();
            } catch (Exception ignored) {}
        }
        if (u instanceof AssignmentStmtSoot) {
            AssignmentStmtSoot asSoot = (AssignmentStmtSoot) u;
            if (asSoot.getAssignStmt() != null && asSoot.getAssignStmt().getRHS() instanceof Call) {
                Call c = (Call) asSoot.getAssignStmt().getRHS();
                if (c.getFunc() instanceof Attribute) {
                    return ((Attribute) c.getFunc()).getAttr();
                } else if (c.getFunc() instanceof Name) {
                    return ((Name) c.getFunc()).getName();
                }
            }
        }
        if (u instanceof AssignStmt) {
            AssignStmt as = (AssignStmt) u;
            if (as.getRHS() instanceof Call) {
                Call c = (Call) as.getRHS();
                if (c.getFunc() instanceof Attribute) {
                    return ((Attribute) c.getFunc()).getAttr();
                } else if (c.getFunc() instanceof Name) {
                    return ((Name) c.getFunc()).getName();
                }
            }
        }
        if (u instanceof CallExprStmt) {
            CallExprStmt cs = (CallExprStmt) u;
            if (cs.getCallExpr() instanceof Call) {
                Call c = (Call) cs.getCallExpr();
                if (c.getFunc() instanceof Attribute) {
                    return ((Attribute) c.getFunc()).getAttr();
                } else if (c.getFunc() instanceof Name) {
                    return ((Name) c.getFunc()).getName();
                }
            }
        }
        try {
            String str = u.toString();
            if (str != null) {
                if (str.contains(".executemany(")) return "executemany";
                if (str.contains(".execute(")) return "execute";
                if (str.contains(".fetchone(")) return "fetchone";
                if (str.contains(".fetchall(")) return "fetchall";
                if (str.contains(".fetchmany(")) return "fetchmany";
            }
        } catch (Exception ignored) {}
        return null;
    }

    public static DbridgeAnalysis.LoopData buildLoopPDG(Body body, BriefUnitGraph graph, Loop loop, String methodName) {
        Stmt head = loop.getHead();
        int headLineno = (head instanceof IStmt) ? ((IStmt) head).getLineno() : -1;

        List<String> testVars = new ArrayList<>();
        for (ValueBox vb : head.getUseBoxes()) {
            String vName = getVarName(vb.getValue());
            if (vName != null && !testVars.contains(vName)) {
                testVars.add(vName);
            }
        }

        List<StmtUnitInfo> loopStmts = new ArrayList<>();
        Set<Unit> loopUnitSet = new HashSet<>(loop.getLoopStatements());

        for (Unit u : body.getUnits()) {
            if (loopUnitSet.contains(u)) {
                loopStmts.add(new StmtUnitInfo(u));
            }
        }
        if (loopStmts.isEmpty()) {
            for (Stmt s : loop.getLoopStatements()) {
                loopStmts.add(new StmtUnitInfo(s));
            }
        }

        return buildLoopPDGHelper(loopStmts, headLineno, testVars, methodName);
    }

    public static DbridgeAnalysis.LoopData buildLoopPDGFromWhileStmt(ir.Stmt.WhileStmtPy wsp, String methodName) {
        int headLineno = wsp.getLineno();
        List<String> testVars = new ArrayList<>();
        if (wsp.getTest() != null) {
            String vName = getVarName(wsp.getTest());
            if (vName != null) {
                testVars.add(vName);
            }
        }
        List<StmtUnitInfo> loopStmts = new ArrayList<>();
        if (wsp.getWhileBody() != null) {
            for (Unit u : wsp.getWhileBody().getUnits()) {
                loopStmts.add(new StmtUnitInfo(u));
            }
        }
        return buildLoopPDGHelper(loopStmts, headLineno, testVars, methodName);
    }

    public static DbridgeAnalysis.LoopData buildLoopPDGHelper(List<StmtUnitInfo> loopStmts, int headLineno, List<String> testVars, String methodName) {
        DbridgeAnalysis.LoopData loopData = new DbridgeAnalysis.LoopData();
        loopData.method = methodName;
        loopData.headLineno = headLineno;
        loopData.testVars = testVars;

        // stmtOrder: positive line numbers in loop body
        Set<Integer> seenLines = new LinkedHashSet<>();
        for (StmtUnitInfo info : loopStmts) {
            if (info.lineno > 0) {
                seenLines.add(info.lineno);
            }
        }
        loopData.stmtOrder = new ArrayList<>(seenLines);

        // PDG dependencies computation
        Set<Dep> depSet = new LinkedHashSet<>();
        int n = loopStmts.size();

        // 1. Intra-loop data dependencies (RAW, WAR, WAW)
        for (int i = 0; i < n; i++) {
            StmtUnitInfo s1 = loopStmts.get(i);
            if (s1.lineno <= 0 && s1.lineno != -10) continue;

            for (int j = i + 1; j < n; j++) {
                StmtUnitInfo s2 = loopStmts.get(j);
                if (s2.lineno <= 0 && s2.lineno != -10) continue;

                // RAW (flow)
                for (String v : s1.defs) {
                    if (s2.uses.contains(v)) {
                        depSet.add(new Dep(s1.lineno, s2.lineno, v, "RAW"));
                    }
                }
                // WAR (anti)
                for (String v : s1.uses) {
                    if (s2.defs.contains(v)) {
                        depSet.add(new Dep(s1.lineno, s2.lineno, v, "WAR"));
                    }
                }
                // WAW (output)
                for (String v : s1.defs) {
                    if (s2.defs.contains(v)) {
                        depSet.add(new Dep(s1.lineno, s2.lineno, v, "WAW"));
                    }
                }
            }
        }

        // 2. Loop-carried dependencies
        for (int i = 0; i < n; i++) {
            StmtUnitInfo s1 = loopStmts.get(i);
            if (s1.lineno <= 0 && s1.lineno != -10) continue;

            for (int j = 0; j < n; j++) {
                StmtUnitInfo s2 = loopStmts.get(j);
                if (s2.lineno <= 0 && s2.lineno != -10) continue;

                for (String v : s1.defs) {
                    if (s2.uses.contains(v)) {
                        depSet.add(new Dep(s1.lineno, s2.lineno, v, "loop_carried"));
                    }
                }
            }
        }

        // 3. Control dependencies
        if (loopData.headLineno > 0) {
            for (StmtUnitInfo s : loopStmts) {
                if (s.lineno > 0 && s.lineno != loopData.headLineno) {
                    depSet.add(new Dep(loopData.headLineno, s.lineno, "", "control"));
                }
            }
        }

        loopData.deps = new ArrayList<>(depSet);

        Set<String> conditionVars = new HashSet<>(loopData.testVars);

        // Per-query self-cyclic detection and classification
        for (int i = 0; i < n; i++) {
            StmtUnitInfo s = loopStmts.get(i);
            if (s.isExecute) {
                DbridgeAnalysis.QueryData qd = new DbridgeAnalysis.QueryData();
                qd.callLineno = s.lineno;

                // 1. Associate query Q with its own fetch statements (fetches before next execute)
                List<StmtUnitInfo> fetchStmts_q = new ArrayList<>();
                for (int j = i + 1; j < n; j++) {
                    StmtUnitInfo next = loopStmts.get(j);
                    if (next.isExecute) {
                        break;
                    }
                    if (next.isFetch) {
                        fetchStmts_q.add(next);
                    }
                }

                // 2. Seed postVars_q solely with definitions from Q's own fetch results
                Set<String> postVars_q = new HashSet<>();
                for (StmtUnitInfo f : fetchStmts_q) {
                    postVars_q.addAll(f.defs);
                }

                // 3. Compute transitive closure of postVars_q
                boolean changed = true;
                while (changed) {
                    changed = false;
                    for (StmtUnitInfo ls : loopStmts) {
                        if (!Collections.disjoint(ls.uses, postVars_q)) {
                            if (postVars_q.addAll(ls.defs)) {
                                changed = true;
                            }
                        }
                    }
                }

                // 4. Query Q is self-cyclic iff a loop_carried dependency flows from postVars_q into Q's parameter variables across iterations
                Set<String> paramVars = new HashSet<>(s.uses);
                boolean isCyclic = false;
                if (!postVars_q.isEmpty()) {
                    for (Dep dep : depSet) {
                        if ("loop_carried".equals(dep.type)) {
                            if ((dep.tgt == qd.callLineno || paramVars.contains(dep.var)) && postVars_q.contains(dep.var)) {
                                isCyclic = true;
                                break;
                            }
                        }
                    }
                }
                qd.cyclic = isCyclic;

                // 5. Classify statements for query Q
                for (StmtUnitInfo ls : loopStmts) {
                    int ln = ls.lineno;
                    if (ln <= 0 && ln != -10) continue;

                    if (ln == qd.callLineno) {
                        qd.labels.put(ln, "EXEC");
                    } else if (ln == loopData.headLineno || !Collections.disjoint(ls.defs, conditionVars)) {
                        qd.labels.put(ln, "ADVANCE");
                    } else if (fetchStmts_q.contains(ls) || !Collections.disjoint(ls.uses, postVars_q) || !Collections.disjoint(ls.defs, postVars_q)) {
                        qd.labels.put(ln, "POST");
                    } else {
                        qd.labels.put(ln, "PRE");
                    }
                }

                loopData.queries.add(qd);
            }
        }

        return loopData;
    }
}
