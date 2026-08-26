"""Bridge to SCIRPy Java static analysis.

Invokes the Java-based SCIRPy analysis via py4j and GatewayServer using JAVA_HOME from .env.
"""
import os
import time
import logging
import subprocess
import atexit
from pathlib import Path
from py4j.java_gateway import JavaGateway, GatewayParameters

# Suppress noisy py4j internal logging during gateway teardown
logging.getLogger("py4j").setLevel(logging.CRITICAL)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCIRPY_JAR_DIR = PROJECT_ROOT / "scirpy" / "out" / "artifacts" / "scirpy_jar"
LIB_DIR = PROJECT_ROOT / "scirpy" / "lib"

_gateway = None
_gateway_proc = None

def load_env_java_home() -> str | None:
    """Read JAVA_HOME from .env file or environment."""
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("JAVA_HOME="):
                val = line.split("=", 1)[1].strip().strip('"').strip("'")
                if val:
                    return val
    return os.environ.get("JAVA_HOME")

def get_java_executable() -> str:
    """Locate java binary from .env / JAVA_HOME or fall back to system java."""
    java_home = load_env_java_home()
    if java_home:
        java_bin = Path(java_home) / "bin" / "java"
        if java_bin.exists():
            return str(java_bin)
    return "java"

def _get_gateway():
    """Get or initialize the persistent Py4J gateway."""
    global _gateway, _gateway_proc
    if _gateway is not None:
        try:
            _gateway.jvm.System.currentTimeMillis()
            return _gateway, _gateway.entry_point
        except Exception:
            _shutdown_gateway()

    main_scirpy_jar = SCIRPY_JAR_DIR / "scirpy.jar"
    all_jars = list(SCIRPY_JAR_DIR.glob("*.jar")) + list(LIB_DIR.glob("*.jar"))
    jars = [main_scirpy_jar] + [j for j in all_jars if j.name != "scirpy.jar"]
    classpath = os.pathsep.join(str(j) for j in jars)
    java_cmd = get_java_executable()

    cmd = [
        java_cmd,
        "-noverify",
        "-cp",
        classpath,
        "PythonGateWay.ScaPaGateway"
    ]
    
    _gateway_proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    _gateway = JavaGateway(gateway_parameters=GatewayParameters(port=25333))

    timeout_sec = float(os.environ.get("PYDBRIDGE_JVM_TIMEOUT", "10.0"))
    max_retries = max(10, int(timeout_sec / 0.1))
    connected = False
    for _ in range(max_retries):
        try:
            _gateway.jvm.System.currentTimeMillis()
            connected = True
            break
        except Exception:
            time.sleep(0.1)

    if not connected:
        try:
            _gateway_proc.terminate()
            _gateway_proc.wait(timeout=1)
        except Exception:
            try:
                _gateway_proc.kill()
            except Exception:
                pass
        _gateway_proc = None
        _gateway = None
        raise RuntimeError("Failed to connect to Py4J gateway")

    return _gateway, _gateway.entry_point

def _shutdown_gateway():
    """Shutdown the persistent Py4J gateway."""
    global _gateway, _gateway_proc
    if _gateway:
        try:
            _gateway.shutdown()
        except Exception as e:
            logging.warning(f"Error shutting down gateway: {e}")
        _gateway = None
    if _gateway_proc:
        try:
            _gateway_proc.terminate()
            _gateway_proc.wait(timeout=1)
        except Exception as e:
            logging.warning(f"Error terminating gateway proc: {e}")
            try:
                _gateway_proc.kill()
            except Exception as e2:
                logging.warning(f"Error killing gateway proc: {e2}")
        _gateway_proc = None

atexit.register(_shutdown_gateway)

def run_scirpy_analysis(json_ast_path: Path, source_name: str,
                        output_dir: Path, data_dir: Path) -> dict:
    """Invoke SCIRPy Java analysis on the JSON AST using Py4J gateway."""
    if os.environ.get("PYDBRIDGE_NO_SCIRPY") == "1":
        return {"facts": {}, "analysis_json_path": None, "opt_code_path": None}
    try:
        gateway, app = _get_gateway()
        timeout = float(os.environ.get("PYDBRIDGE_JVM_TIMEOUT", "10.0"))
        
        import threading
        
        analysis_json_path = output_dir / "analysis.json"
        opt_code_path = output_dir / f"Opt_Code_{source_name}.py"
        if analysis_json_path.exists():
            try:
                analysis_json_path.unlink()
            except Exception:
                pass
        if opt_code_path.exists():
            try:
                opt_code_path.unlink()
            except Exception:
                pass

        class ExecThread(threading.Thread):
            def __init__(self):
                super().__init__()
                self.status = -1
                self.exc = None
            def run(self):
                try:
                    self.status = app.runIPMain(
                        str(json_ast_path),
                        source_name,
                        str(output_dir),
                        str(data_dir)
                    )
                except Exception as e:
                    self.exc = e

        t = ExecThread()
        t.start()
        t.join(timeout)
        
        if t.is_alive():
            raise TimeoutError(f"SCIRPy analysis timed out after {timeout} seconds")
        if t.exc:
            raise t.exc
        
        status = t.status
        facts = {}
        analysis_json_path = output_dir / "analysis.json"
        opt_code_path = output_dir / f"Opt_Code_{source_name}.py"
        
        if analysis_json_path.exists():
            try:
                import json
                raw_text = analysis_json_path.read_text(encoding="utf-8").strip()
                if raw_text:
                    try:
                        facts = json.loads(raw_text)
                    except Exception:
                        dec = json.JSONDecoder()
                        obj, _ = dec.raw_decode(raw_text)
                        facts = obj
            except Exception as e:
                logging.warning(f"Failed to parse analysis JSON: {e}")

        return {
            "facts": facts,
            "analysis_json_path": str(analysis_json_path) if analysis_json_path.exists() else None,
            "opt_code_path": str(opt_code_path) if opt_code_path.exists() else None
        }
    except Exception as exc:
        msg = f"SCIRPy execution error: {type(exc).__name__}: {exc}"
        raise RuntimeError(msg) from None

def eqsql_optimize_query(sql_query: str, db_type: str = "sqlite") -> str:
    """Optimize SQL queries using EqSQL."""
    try:
        gateway, app = _get_gateway()
        optimized_query = app.optimizeQuery(sql_query, db_type)
        if optimized_query and optimized_query != sql_query:
            return str(optimized_query)
        return sql_query
    except Exception as exc:
        try:
            _shutdown_gateway()
            gateway, app = _get_gateway()
            optimized_query = app.optimizeQuery(sql_query, db_type)
            if optimized_query and optimized_query != sql_query:
                return str(optimized_query)
            return sql_query
        except Exception as retry_exc:
            logging.warning(f"EqSQL optimization error: {retry_exc}")
            return sql_query
