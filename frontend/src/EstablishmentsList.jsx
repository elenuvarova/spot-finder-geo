// The "establishments behind the score" transparency view. Lists the actual
// points mapped inside the selected sector, grouped by kind, so the choropleth
// score is auditable rather than a black box.

const DIET_CHIPS = [
  { key: 'diet_vegan', emoji: '🌱', label: 'vegan' },
  { key: 'diet_vegetarian', emoji: '🥗', label: 'vegetarian' },
  { key: 'diet_glutenfree', emoji: '🌾', label: 'gluten-free' },
  { key: 'diet_halal', emoji: '🕌', label: 'halal' },
];

// Each point lands in the FIRST group whose match() returns true. Order matters.
const GROUPS = [
  { id: 'cafe', heading: 'Coffee', match: (p) => p.spot_type === 'cafe' },
  { id: 'bakery', heading: 'Bakeries', match: (p) => p.spot_type === 'bakery' },
  {
    id: 'confectionery',
    heading: 'Confectioneries',
    match: (p) => p.spot_type === 'confectionery',
  },
  {
    id: 'gastro',
    heading: 'Restaurants & fast food',
    match: (p) => p.is_gastro && p.spot_type == null,
  },
  {
    id: 'retail',
    heading: 'Shops',
    match: (p) => p.is_retail && p.spot_type == null && !p.is_gastro,
  },
  {
    id: 'transit',
    heading: 'Transit',
    match: (p) =>
      p.is_transit && p.spot_type == null && !p.is_gastro && !p.is_retail,
  },
  {
    id: 'office',
    heading: 'Offices & education',
    match: (p) =>
      p.is_office &&
      p.spot_type == null &&
      !p.is_gastro &&
      !p.is_retail &&
      !p.is_transit,
  },
];

// Maps the selected business `type` to the group that should be highlighted.
const FOCUS_GROUP = {
  cafe: 'cafe',
  bakery: 'bakery',
  confectionery: 'confectionery',
};

// Per-group chip caps. The focus group (the type you're scoring for) shows
// more of its members so "how many competitors of my type are already here"
// is answerable at a glance; ancillary groups stay dense and scannable.
const FOCUS_MAX_ITEMS = 12;
const OTHER_MAX_ITEMS = 6;

function dietChips(point) {
  return DIET_CHIPS.filter((chip) => point[chip.key]).map((chip) => (
    <span key={chip.key} className="diet-chip" title={chip.label}>
      {chip.emoji}
    </span>
  ));
}

export default function EstablishmentsList({ points, type }) {
  if (!points || points.length === 0) {
    return (
      <p className="establishments__empty">
        No mapped establishments in this sector.
      </p>
    );
  }

  // Assign every point to the first group it qualifies for.
  const buckets = GROUPS.map((group) => ({ group, items: [] }));
  points.forEach((point) => {
    const bucket = buckets.find((b) => b.group.match(point));
    if (bucket) bucket.items.push(point);
  });

  const focusGroup = FOCUS_GROUP[type];

  return (
    <div className="establishments">
      <p className="establishments__summary">
        {points.length} places mapped here
      </p>
      {buckets
        .filter((b) => b.items.length > 0)
        .map(({ group, items }) => {
          const isFocus = group.id === focusGroup;
          const cap = isFocus ? FOCUS_MAX_ITEMS : OTHER_MAX_ITEMS;
          const named = items.filter((p) => p.name);
          const shown = named.slice(0, cap);
          // Everything not shown as a named chip — folds unnamed places and the
          // overflow of named places into one honest "+N more" count.
          const remaining = items.length - shown.length;
          return (
            <div
              key={group.id}
              className={`establishments__group${
                isFocus ? ' is-focus' : ''
              }`}
            >
              <h4
                className={`establishments__heading${
                  isFocus ? ' is-focus-type' : ''
                }`}
              >
                {group.heading} <span>({items.length})</span>
              </h4>
              <div className="establishments__items">
                {shown.map((point, i) => (
                  <span key={i} className="establishments__item">
                    <span className="establishments__name">{point.name}</span>
                    {dietChips(point)}
                  </span>
                ))}
                {/* A group with zero named places reads as a single ghost chip
                    instead of a bare "+N more" with nothing above it. */}
                {shown.length === 0 && remaining > 0 && (
                  <span className="establishments__item establishments__item--ghost">
                    {remaining} unnamed
                  </span>
                )}
                {shown.length > 0 && remaining > 0 && (
                  <span className="establishments__item establishments__item--ghost">
                    +{remaining} more
                  </span>
                )}
              </div>
            </div>
          );
        })}
    </div>
  );
}
