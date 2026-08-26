package PythonGateWay;
import analysis.interprocedural.IPMain;
import py4j.GatewayServer;

public class ScaPaGateway {
    public String runIPMain(String sourceNameFull, String sourceFileName, String destinationPath, String dataPath) {
        //runIPMain(source_name_full_json,file_name,opt_path)
       // IPMain.main(null);
        System.out.println(sourceNameFull+"\n"+sourceFileName+"\n"+destinationPath);
        ScaPaOptimizations.setPaths(sourceNameFull,sourceFileName,destinationPath,dataPath);
        ScaPaOptimizations.main(null);
        return destinationPath + "/analysis.json";
    }

    public String optimizeQuery(String sql, String dbType) {
        return dbridge.eqsql.EqSQLHelper.optimizeQuery(sql, dbType);
    }

    public static void main(String[] args) {
        ScaPaGateway gateway=new ScaPaGateway();
        // app is now the gateway.entry_point
        GatewayServer server = new GatewayServer(gateway);
        server.start();
    }
}
