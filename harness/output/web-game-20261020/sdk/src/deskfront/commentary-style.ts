/** Reject a paraphrased replay; never replace the model's words with a script. */
export function commentaryTooSimilar(text: string, previous: string[]): boolean {
  const normalize = (value: string) => value.replace(/[^\p{L}\p{N}]/gu, '');
  const pairs = (value: string) => new Set(Array.from(value).slice(1).map((c, i) => value[i]! + c));
  const current = normalize(text);
  return previous.some(value => {
    const old = normalize(value);
    if (current === old) return true;
    // A changed explicit count can be a real update, even in a similar phrase.
    if (current.match(/\d+(?:\.\d+)?|[零〇一二两三四五六七八九十百千万]+(?=[名个辆门件段人条])/gu)?.join(',') !== old.match(/\d+(?:\.\d+)?|[零〇一二两三四五六七八九十百千万]+(?=[名个辆门件段人条])/gu)?.join(',')) return false;
    if (current.match(/坦克|迫击炮手|迫击炮|火箭筒|冲锋枪|步枪|左上|左下|右上|右下|左侧|右侧|中列|上方|下方|中部|中央桌面|前方|后方|入口|出口/gu)?.join(',') !== old.match(/坦克|迫击炮手|迫击炮|火箭筒|冲锋枪|步枪|左上|左下|右上|右下|左侧|右侧|中列|上方|下方|中部|中央桌面|前方|后方|入口|出口/gu)?.join(',')) return false;
    if (current.match(/不再|不|没有|未|取消|撤销|恢复|延后|提前|增加|减少|改为/gu)?.join(',') !== old.match(/不再|不|没有|未|取消|撤销|恢复|延后|提前|增加|减少|改为/gu)?.join(',')) return false;
    if (Math.min(current.length, old.length) < 8) return false;
    const a = pairs(current), b = pairs(old);
    const intersection = [...a].filter(pair => b.has(pair)).length;
    return intersection / (a.size + b.size - intersection) >= .55
      || intersection / Math.min(a.size, b.size) >= .72;
  });
}
