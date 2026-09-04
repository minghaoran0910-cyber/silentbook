/* SilentBook Tasker JavaScriptlet：HMAC-SHA256 签名（纯 JS，无外部依赖）
 * 用法（Tasker JavaScriptlet action 内）：
 *   输入 Tasker 变量：%SB_SECRET, %SB_TS, %SB_BODY
 *   输出：%SB_SIG （sha256= 开头的十六进制签名）
 * 本文件同时可在 Node 下自测：node tasker-hmac.cjs selftest
 * （扩展名必须是 .cjs：家目录 package.json 是 type:module，
 *  .js 会被当 ESM 跑导致自测分支静默跳过）
 */
function sb_sha256(ascii) {
  function rr(v, a) { return (v >>> a) | (v << (32 - a)); }
  var maxWord = Math.pow(2, 32), result = '';
  var words = [], bitLen = ascii.length * 8;
  var hash = [0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
              0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19];
  var k = [0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2];
  ascii += '\x80';
  while (ascii.length % 64 - 56) ascii += '\x00';
  for (var i = 0; i < ascii.length; i++) {
    var j = ascii.charCodeAt(i);
    if (j >> 8) return '';
    words[i >> 2] |= j << ((3 - i) % 4) * 8;
  }
  words[words.length] = (bitLen / maxWord) | 0;
  words[words.length] = bitLen;
  for (var j = 0; j < words.length;) {
    var w = words.slice(j, j + 16);
    var oldHash = hash.slice(0);
    for (var i = 0; i < 64; i++) {
      var w15 = w[i - 15], w2 = w[i - 2];
      var a = hash[0], e = hash[4];
      var t1 = hash[7] + (rr(e, 6) ^ rr(e, 11) ^ rr(e, 25)) + ((e & hash[5]) ^ (~e & hash[6])) + k[i]
        + (w[i] = i < 16 ? w[i] : (w[i - 16] + (rr(w15, 7) ^ rr(w15, 18) ^ (w15 >>> 3)) + w[i - 7] + (rr(w2, 17) ^ rr(w2, 19) ^ (w2 >>> 10))) | 0);
      var t2 = (rr(a, 2) ^ rr(a, 13) ^ rr(a, 22)) + ((a & hash[1]) ^ (a & hash[2]) ^ (hash[1] & hash[2]));
      hash = [(t1 + t2) | 0].concat(hash);
      hash[4] = (hash[4] + t1) | 0;
    }
    for (var i = 0; i < 8; i++) hash[i] = (hash[i] + oldHash[i]) | 0;
    j += 16;
  }
  for (var i = 0; i < 8; i++) {
    for (var j = 3; j + 1; j--) {
      var b = (hash[i] >> (j * 8)) & 255;
      result += (b < 16 ? '0' : '') + b.toString(16);
    }
  }
  return result;
}

function sb_hex2bin(hex) {
  var s = '';
  for (var i = 0; i < hex.length; i += 2) {
    s += String.fromCharCode(parseInt(hex.substr(i, 2), 16));
  }
  return s;
}

function sb_hmac_sha256(key, msg) {
  function utf8(s) { return unescape(encodeURIComponent(s)); }
  key = utf8(key); msg = utf8(msg);
  if (key.length > 64) key = sb_hex2bin(sb_sha256(key));
  var o = '', ip = '';
  for (var i = 0; i < 64; i++) {
    var c = i < key.length ? key.charCodeAt(i) : 0;
    o += String.fromCharCode(c ^ 0x5c);
    ip += String.fromCharCode(c ^ 0x36);
  }
  // 内层摘要必须是原始字节（hex 先转回二进制），不能直接拼 hex 串
  return sb_sha256(o + sb_hex2bin(sb_sha256(ip + msg)));
}

// ---- Tasker 入口（在 Tasker 里把下面 3 行粘进 JavaScriptlet，上面函数原样保留） ----
// var __sig = 'sha256=' + sb_hmac_sha256(SB_SECRET, SB_TS + '.' + SB_BODY);
// setGlobal('SB_SIG', __sig);

if (typeof module !== 'undefined' && process && process.argv.indexOf('selftest') >= 0) {
  var assert = require('assert');
  assert.strictEqual(sb_sha256('abc'), 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad');
  assert.strictEqual(sb_hmac_sha256('key', 'The quick brown fox jumps over the lazy dog'),
    'f7bc83f430538424b13298e6aa6fb143ef4d59a14946175997479dbc2d1a3cd8');
  // 与 Python hmac 交叉验证由 CI/调用方执行，这里只做空输入冒烟
  assert.strictEqual(sb_hmac_sha256('', '').length, 64);
  console.log('tasker-hmac selftest OK');
}
