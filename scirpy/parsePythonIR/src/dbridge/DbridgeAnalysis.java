package dbridge;

import soot.Body;
import soot.SootClass;
import soot.SootMethod;
import soot.Unit;
import soot.ValueBox;
import soot.toolkits.graph.BriefUnitGraph;
import soot.toolkits.graph.LoopNestTree;
import soot.jimple.toolkits.annotation.logic.Loop;

import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.ArrayList;

public class DbridgeAnalysis {
    public Map<String, MethodSummary> methodSummaries = new HashMap<>();
    public Map<String, Object> typedRegionTrees = new HashMap<>();
    public List<LoopData> loops = new ArrayList<>();

    public static class MethodSummary {
        public boolean mayRead = false;
        public boolean mayWrite = false;
        public boolean hasFetch = false;
        public boolean returnsValue = false;
    }

    public static class QueryData {
        public int callLineno;
        public boolean cyclic = false;
        public Map<Integer, String> labels = new HashMap<>();
    }

    public static class LoopData {
        public String method;
        public int headLineno;
        public List<String> testVars = new ArrayList<>();
        public List<Integer> stmtOrder = new ArrayList<>();
        public List<DbridgePDG.Dep> deps = new ArrayList<>();
        public List<QueryData> queries = new ArrayList<>();
    }

    public DbridgeAnalysis(List<SootClass> classes) {
        for (SootClass sc : classes) {
            for (SootMethod sm : sc.getMethods()) {
                MethodSummary ms = computeMethodSummary(sm);
                methodSummaries.put(sm.getName(), ms);

                if (!sm.hasActiveBody()) {
                    try {
                        sm.retrieveActiveBody();
                    } catch (Exception ignored) {}
                }
                if (!sm.hasActiveBody()) continue;

                Body body = sm.getActiveBody();
                BriefUnitGraph graph = new BriefUnitGraph(body);
                try {
                    LoopNestTree loopNestTree = new LoopNestTree(body);
                    for (Loop loop : loopNestTree) {
                        LoopData loopData = DbridgePDG.buildLoopPDG(body, graph, loop, sm.getName());
                        loops.add(loopData);
                    }
                } catch (Throwable ignored) {}

                List<Unit> unitList = new ArrayList<>();
                for (Unit u : body.getUnits()) {
                    unitList.add(u);
                }

                for (int uIdx = 0; uIdx < unitList.size(); uIdx++) {
                    Unit u = unitList.get(uIdx);
                    if (u instanceof ir.Stmt.IfStmt) {
                        ir.Stmt.IfStmt ifStmt = (ir.Stmt.IfStmt) u;
                        String uStr = u.toString().trim();
                        if (uStr.startsWith("while") || uStr.startsWith("for")) {
                            int headLineno = ifStmt.getLineno();
                            boolean alreadyFound = false;
                            for (LoopData ld : loops) {
                                if (ld.headLineno == headLineno && headLineno > 0) {
                                    alreadyFound = true;
                                    break;
                                }
                            }
                            if (!alreadyFound) {
                                List<String> testVars = new ArrayList<>();
                                for (ValueBox vb : ifStmt.getUseBoxes()) {
                                    String vName = DbridgePDG.getVarName(vb.getValue());
                                    if (vName != null && !testVars.contains(vName)) {
                                        testVars.add(vName);
                                    }
                                }
                                Unit targetUnit = ifStmt.getTarget();
                                List<DbridgePDG.StmtUnitInfo> loopStmts = new ArrayList<>();
                                for (int j = uIdx + 1; j < unitList.size(); j++) {
                                    Unit bodyUnit = unitList.get(j);
                                    if (targetUnit != null && bodyUnit == targetUnit) {
                                        break;
                                    }
                                    loopStmts.add(new DbridgePDG.StmtUnitInfo(bodyUnit));
                                }
                                if (!loopStmts.isEmpty()) {
                                    LoopData loopData = DbridgePDG.buildLoopPDGHelper(loopStmts, headLineno, testVars, sm.getName());
                                    loops.add(loopData);
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    public static MethodSummary computeMethodSummary(SootMethod sm) {
        MethodSummary ms = new MethodSummary();
        if (sm.getReturnType() != null &&
            !sm.getReturnType().toString().equals("void") &&
            !(sm.getReturnType() instanceof soot.VoidType)) {
            ms.returnsValue = true;
        }

        if (sm.hasActiveBody()) {
            Body body = sm.getActiveBody();
            for (Unit u : body.getUnits()) {
                if (u instanceof soot.jimple.ReturnStmt) {
                    ms.returnsValue = true;
                }
                String mName = DbridgePDG.getCalledMethodName(u);
                if (mName != null) {
                    if (mName.equals("fetchone") || mName.equals("fetchall") || mName.equals("fetchmany")) {
                        ms.hasFetch = true;
                        ms.mayRead = true;
                    } else if (mName.equals("executemany")) {
                        ms.mayWrite = true;
                    }
                }
                if (u == null) continue;
                try {
                    String uStr = u.toString();
                    if (uStr != null) {
                        uStr = uStr.toUpperCase();
                        if (uStr.contains("SELECT")) {
                            ms.mayRead = true;
                        }
                        if (uStr.contains("INSERT") || uStr.contains("UPDATE") || uStr.contains("DELETE") ||
                            uStr.contains("CREATE") || uStr.contains("DROP") || uStr.contains("ALTER") || uStr.contains("REPLACE")) {
                            ms.mayWrite = true;
                        }
                    }
                } catch (Exception ignored) {}
            }
        }
        return ms;
    }
}
