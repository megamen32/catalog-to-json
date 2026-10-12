"""Run the delivery worker adapter against an explicitly selected installed agent core."""
import argparse
import importlib.util
from pathlib import Path
import sys
import json,hashlib


def main():
    parser=argparse.ArgumentParser(add_help=False);parser.add_argument('--adapter',type=Path,required=True);parser.add_argument('--describe',action='store_true')
    args,remaining=parser.parse_known_args()
    # The original runtime owns catalog_json.agents/tools/provenance and skills.
    # Only delivery receipts/pacing instrumentation are supplied by the adapter.
    spec=importlib.util.spec_from_file_location('catalog_json._delivery_worker_adapter',args.adapter)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    if args.describe:
        from catalog_json.schema import PageContent,Review
        print(json.dumps({'program':module.program_version(),'adapter_sha256':hashlib.sha256(args.adapter.read_bytes()).hexdigest(),
                          'schemas':{cls.__name__:hashlib.sha256(json.dumps(cls.model_json_schema(),sort_keys=True).encode()).hexdigest() for cls in (PageContent,Review)}}));return 0
    sys.argv=[str(args.adapter),*remaining]
    return module.main()


if __name__=='__main__':raise SystemExit(main())
