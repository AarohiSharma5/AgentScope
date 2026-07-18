// Primary "Application / area" filter, shared by Requests and Agent Runs.
//
// `areas` is the facet list from the backend ({type, value, label, count,
// system_prompt, system_prompt_variants}). The <select> value is the index into
// `areas` ("" = all) so the caller can look the selected area object back up
// (its value/type may contain characters that make a poor option value).
export default function AreaSelect({ areas, value, onChange, className = "" }) {
  const projectAreas = areas.filter((a) => a.type === "project");
  const promptAreas = areas.filter((a) => a.type === "system_prompt");
  return (
    <select
      aria-label="Filter by application / area"
      value={value}
      onChange={onChange}
      className={`rounded-lg border border-ink-500 bg-ink-800 px-3 py-2 text-sm text-gray-200 outline-none focus:border-accent ${className}`}
    >
      <option value="">All applications</option>
      {projectAreas.length > 0 && (
        <optgroup label="Applications">
          {projectAreas.map((a) => (
            <option key={`p-${a.value}`} value={String(areas.indexOf(a))}>
              {a.label} ({a.count})
            </option>
          ))}
        </optgroup>
      )}
      {promptAreas.length > 0 && (
        <optgroup label="Untagged — grouped by system prompt">
          {promptAreas.map((a) => (
            <option key={`s-${a.value}`} value={String(areas.indexOf(a))}>
              {a.label} ({a.count})
            </option>
          ))}
        </optgroup>
      )}
    </select>
  );
}
