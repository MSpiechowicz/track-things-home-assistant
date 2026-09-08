/** Replay Python contract fixtures against a local backend checkout (no network). */
const backendRoot = Deno.args[0];
if (!backendRoot?.startsWith("/") || Deno.args.length !== 1) {
  throw new Error(
    "Pass the absolute path of the track-things-backend checkout.",
  );
}
const backendUrl = new URL("file:///");
backendUrl.pathname = `${backendRoot}/src/api/shared/tracker_values.ts`;
const { validateEntryValues } = await import(backendUrl.href);
const fixtureUrl = new URL(
  "../tests/fixtures/schema_contract.json",
  import.meta.url,
);
const cases = JSON.parse(await Deno.readTextFile(fixtureUrl));
for (const test of cases) {
  let actual = null;
  try {
    validateEntryValues(test.values, test.schema);
  } catch (error) {
    if (!(error instanceof Error) || !("code" in error)) throw error;
    actual = error.code;
  }
  if (actual !== test.error) {
    throw new Error(`${test.name}: expected ${test.error}, got ${actual}`);
  }
}
console.log(`${cases.length} schema contract cases match the backend runtime.`);
