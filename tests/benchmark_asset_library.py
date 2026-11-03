"""Benchmark a read-only source snapshot with an isolated, disposable cache."""
import json
from pathlib import Path
import shutil
import sys
import tempfile
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.core.assets import AssetLibrary
from src.core.asset_index import AssetIndex


def main():
    library=AssetLibrary(ROOT)
    start=time.perf_counter();assets=library.scan()
    results={'assets':len(assets),'full_scan_seconds':time.perf_counter()-start}
    # Keep the active app's cache and source files untouched.
    with tempfile.TemporaryDirectory(prefix='asset-benchmark-') as directory:
        target=Path(directory)
        for item in assets:
            destination=target/item['id'];destination.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(library.path(item['id']),destination)
        cold=AssetIndex(target)
        start=time.perf_counter();cold.refresh()
        results['cold_framework_ready_seconds']=time.perf_counter()-start
        while not cold.snapshot()[0]: time.sleep(.005)
        results['cold_first_verified_seconds']=time.perf_counter()-start
        cold.queue.join()
        results['cold_complete_seconds']=time.perf_counter()-start
        cold.close()
        start=time.perf_counter();warm=AssetIndex(target);warm.refresh()
        results['warm_list_seconds']=time.perf_counter()-start
        assert len(warm.snapshot()[0])==len(assets)
        warm.close()
    results={key:round(value,3) if isinstance(value,float) else value for key,value in results.items()}
    output=ROOT/'.artifacts/software_checks/asset_performance.json'
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(results,ensure_ascii=False))


if __name__=='__main__':main()
