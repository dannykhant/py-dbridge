package dbridge;

import org.json.simple.JSONArray;
import org.json.simple.JSONObject;
import soot.Body;
import soot.SootClass;
import soot.SootMethod;
import soot.Unit;
import soot.ValueBox;
import soot.toolkits.graph.BriefUnitGraph;
import soot.toolkits.scalar.FlowSet;
import analysis.LiveVariable.LiveVariableAnalysis;
import ir.IStmt;

import java.io.FileWriter;
import java.io.IOException;
import java.util.List;

public class AnalysisExporter {
    public static void export(List<SootClass> sootClasses, String analysisOutPath) {
        export(sootClasses, analysisOutPath, null);
    }

    public static void export(List<SootClass> sootClasses, String analysisOutPath, DbridgeAnalysis dbridgeAnalysis) {
        JSONObject root = new JSONObject();
        root.put("version", 2);
        JSONArray classesArray = new JSONArray();

        for (SootClass sc : sootClasses) {
            JSONObject classObj = new JSONObject();
            classObj.put("name", sc.getName());
            classObj.put("className", sc.getName());
            JSONArray methodsArray = new JSONArray();

            for (SootMethod sm : sc.getMethods()) {
                try {
                    Body body = null;
                    if (sm.hasActiveBody()) {
                        body = sm.getActiveBody();
                    } else {
                        try {
                            body = sm.retrieveActiveBody();
                        } catch (Exception exc) {
                            continue;
                        }
                    }
                    if (body == null) continue;
                    
                    JSONObject methodObj = new JSONObject();
                    methodObj.put("name", sm.getName());
                    methodObj.put("methodName", sm.getName());
                    JSONArray stmtsArray = new JSONArray();
                    
                    BriefUnitGraph graph = new BriefUnitGraph(body);
                    LiveVariableAnalysis lva = new LiveVariableAnalysis(graph);
                    
                    java.util.Map<Integer, JSONObject> linenoToStmt = new java.util.HashMap<>();
                    
                    for (Unit u : body.getUnits()) {
                        int lineno = -1;
                        if (u instanceof IStmt) {
                            lineno = ((IStmt) u).getLineno();
                        }
                        
                        // Handle sentinels
                        if (lineno <= 0 && lineno != -10) continue;
                        
                        JSONObject stmtObj = linenoToStmt.get(lineno);
                        if (stmtObj == null) {
                            stmtObj = new JSONObject();
                            stmtObj.put("lineno", lineno);
                            stmtObj.put("unitString", u.toString());
                            stmtObj.put("defs", new JSONArray());
                            stmtObj.put("uses", new JSONArray());
                            stmtObj.put("liveBefore", new JSONArray());
                            linenoToStmt.put(lineno, stmtObj);
                            stmtsArray.add(stmtObj);
                        }
                        
                        JSONArray defs = (JSONArray) stmtObj.get("defs");
                        for (ValueBox vb : u.getDefBoxes()) {
                            String nameStr = vb.getValue().toString();
                            if (!defs.contains(nameStr)) defs.add(nameStr);
                        }
                        
                        JSONArray uses = (JSONArray) stmtObj.get("uses");
                        for (ValueBox vb : u.getUseBoxes()) {
                            String nameStr = vb.getValue().toString();
                            if (!uses.contains(nameStr)) uses.add(nameStr);
                        }
                        
                        JSONArray liveBefore = (JSONArray) stmtObj.get("liveBefore");
                        FlowSet flowBefore = (FlowSet) lva.getFlowBefore(u);
                        if (flowBefore != null) {
                            for (Object v : flowBefore) {
                                String nameStr = v.toString();
                                if (!liveBefore.contains(nameStr)) liveBefore.add(nameStr);
                            }
                        }
                    }
                    
                    if (dbridgeAnalysis != null) {
                        DbridgeAnalysis.MethodSummary ms = dbridgeAnalysis.methodSummaries.get(sm.getName());
                        if (ms != null) {
                            JSONObject msObj = new JSONObject();
                            msObj.put("mayRead", ms.mayRead);
                            msObj.put("mayWrite", ms.mayWrite);
                            msObj.put("hasFetch", ms.hasFetch);
                            msObj.put("returnsValue", ms.returnsValue);
                            methodObj.put("methodSummary", msObj);
                        }
                    }
                    
                    methodObj.put("statements", stmtsArray);
                    methodsArray.add(methodObj);
                } catch (Throwable t) {
                    System.err.println("[AnalysisExporter] Warning for method " + sm.getName() + ": " + t.getMessage());
                }
            }
            classObj.put("methods", methodsArray);
            classesArray.add(classObj);
        }
        
        root.put("classes", classesArray);
        
        if (dbridgeAnalysis != null) {
            JSONArray loopsArray = new JSONArray();
            for (DbridgeAnalysis.LoopData ld : dbridgeAnalysis.loops) {
                JSONObject loopObj = new JSONObject();
                loopObj.put("method", ld.method);
                loopObj.put("headLineno", ld.headLineno);
                
                JSONArray testVars = new JSONArray();
                testVars.addAll(ld.testVars);
                loopObj.put("testVars", testVars);

                JSONArray stmtOrder = new JSONArray();
                stmtOrder.addAll(ld.stmtOrder);
                loopObj.put("stmtOrder", stmtOrder);

                JSONArray depsArray = new JSONArray();
                for (DbridgePDG.Dep dep : ld.deps) {
                    JSONObject depObj = new JSONObject();
                    depObj.put("src", dep.src);
                    depObj.put("tgt", dep.tgt);
                    depObj.put("var", dep.var);
                    depObj.put("type", dep.type);
                    depsArray.add(depObj);
                }
                loopObj.put("deps", depsArray);
                
                JSONArray queriesArray = new JSONArray();
                for (DbridgeAnalysis.QueryData qd : ld.queries) {
                    JSONObject queryObj = new JSONObject();
                    queryObj.put("callLineno", qd.callLineno);
                    queryObj.put("cyclic", qd.cyclic);
                    
                    JSONObject labelsObj = new JSONObject();
                    for (java.util.Map.Entry<Integer, String> lblEntry : qd.labels.entrySet()) {
                        labelsObj.put(lblEntry.getKey().toString(), lblEntry.getValue());
                    }
                    queryObj.put("labels", labelsObj);
                    
                    queriesArray.add(queryObj);
                }
                loopObj.put("queries", queriesArray);
                loopsArray.add(loopObj);
            }
            root.put("loops", loopsArray);
            
            JSONObject regionTrees = new JSONObject();
            for (java.util.Map.Entry<String, Object> entry : dbridgeAnalysis.typedRegionTrees.entrySet()) {
                regionTrees.put(entry.getKey(), entry.getValue().toString());
            }
            root.put("typedRegionTrees", regionTrees);
        }
        
        try (FileWriter file = new FileWriter(analysisOutPath)) {
            file.write(root.toJSONString());
            file.flush();
        } catch (IOException e) {
            e.printStackTrace();
        }
    }
}
