#!/bin/bash
# CMD-WUG1 S1: 진짜 Gemini CLI 를 가짜 모델(fakeloop.py)에 붙여 한 세션을 길게 돌리고, 매 초 강제 GC 뒤의 남은 힙을 적는다.
# 무료 한도를 안 쓴다(모델은 가짜). 확장의 MCP 서버(wug_mcp.py)는 진짜다.
# usage: heapbench/run.sh NAME PORT
#   env: TURNS MODE(tool|text) TOOL ARGS_LIST(JSON 배열) DELAY PREP_FILES EXTRA_SETTINGS NODE_EXTRA HEAPLOG_EVERY HEAPSNAP_AT_MB
#        GEMINI_JS(기본: PATH 의 gemini 가 가리키는 bundle/gemini.js) OUT(기본 ./heapbench-out) WUG_DIR WUG_HOME
HB=$(cd "$(dirname "$0")" && pwd)
NAME=$1; PORT=$2; D=${OUT:-$PWD/heapbench-out}/$NAME; rm -rf $D; mkdir -p $D/home/.gemini $D/work
WH=${WUG_HOME:-$HOME/.cache/well_used_gemini}
WD=${WUG_DIR:-$(cd "$HB/.." && pwd)}
GEMINI_JS=${GEMINI_JS:-$(python3 -c "import os,shutil;print(os.path.realpath(shutil.which('gemini') or ''))")}
cat > $D/home/.gemini/settings.json <<JSON
{"security":{"auth":{"selectedType":"gemini-api-key"}},"model":{"name":"gemini-3-flash-preview"},
 "mcpServers":{"agentic":{"command":"python3","args":["$WD/wug_mcp.py"],"cwd":"$WD",
   "env":{"WUG_HOME":"$WH","WUG_NO_GH_CLI":"1","GITHUB_TOKEN":"${GITHUB_TOKEN:-}"},"timeout":600000}}${EXTRA_SETTINGS:-}}
JSON
if [ -n "${PREP_FILES:-}" ]; then python3 -c "
import sys
for i in range(int(sys.argv[1])):
    open(f'$D/work/f{i:03d}.txt','w').write(''.join(f'line {j:05d} of file {i:03d} -- padding padding padding\\n' for j in range(330)))
" $PREP_FILES; fi
python3 $HB/fakeloop.py $PORT $D/api.log > $D/fake.out 2>&1 &
FP=$!; sleep 1
cd $D/work
env HOME=$D/home GEMINI_API_KEY=AIzaFAKEFAKEFAKE GOOGLE_GEMINI_BASE_URL=http://127.0.0.1:$PORT NO_PROXY=127.0.0.1 no_proxy=127.0.0.1 \
  HEAPLOG=$D/heap.log NODE_OPTIONS="--expose-gc --require $HB/heaplog.cjs ${NODE_EXTRA:-}" \
  timeout ${TMO:-3000} node $GEMINI_JS -p "start" -m gemini-3-flash-preview -o json --skip-trust --approval-mode yolo \
  > $D/out.json 2> $D/err.txt
echo "exit=$?" > $D/exit.txt
kill $FP 2>/dev/null
