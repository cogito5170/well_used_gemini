const fs = require('fs'); const v8 = require('v8'); const out = process.env.HEAPLOG;
const snapAt = Number(process.env.HEAPSNAP_AT_MB || 0); let snapped = false;
if (out) { const tick = () => { try { if (global.gc) global.gc(); const m = process.memoryUsage();
  fs.appendFileSync(out, JSON.stringify({pid: process.pid, t: Date.now() / 1000, heap: m.heapUsed, rss: m.rss, ext: m.external, ab: m.arrayBuffers}) + '\n');
  if (snapAt && !snapped && m.heapUsed > snapAt * 2**20) { snapped = true;
    const p = v8.writeHeapSnapshot((process.env.HEAPSNAP_DIR || '.') + '/at' + snapAt + '-' + process.pid + '.heapsnapshot');
    fs.appendFileSync(out, JSON.stringify({pid: process.pid, t: Date.now() / 1000, snapshot: p}) + '\n'); }
  } catch (e) {} }; const h = setInterval(tick, 1000 * Number(process.env.HEAPLOG_EVERY || 1)); h.unref(); }
