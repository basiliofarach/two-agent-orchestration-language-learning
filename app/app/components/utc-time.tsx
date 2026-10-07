/**
 * A recorded instant, shown in UTC (DEC-0010). Formatted without `Intl` so the
 * server render and the hydrated client render are byte-identical.
 */
export function UtcTime({ iso }: { iso: string }) {
  const utc = new Date(iso).toISOString();
  return (
    <time dateTime={utc}>{`${utc.slice(0, 10)} ${utc.slice(11, 16)} UTC`}</time>
  );
}
