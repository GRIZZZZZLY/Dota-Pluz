import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useItem, useItems } from "../api/hooks";
import { ErrorBox, HeroChip, ItemIcon, Loading, Segmented } from "../components/common";
import { clock, gold, pct } from "../lib/format";

const BANDS = [
  { label: "До 500", max: 500 },
  { label: "От 500 до 2000", max: 2000 },
  { label: "От 2000 до 4000", max: 4000 },
  { label: "Больше 4000", max: Infinity },
];

export function ItemsPage() {
  const { data, error } = useItems();
  const [query, setQuery] = useState("");
  const [kind, setKind] = useState<"shop" | "neutral">("shop");
  const list = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (data ?? []).filter((i) => (kind === "neutral" ? i.tier !== null : i.tier === null && i.cost > 0) && (!q || i.name.toLowerCase().includes(q)));
  }, [data, query, kind]);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Предметы</h1>
          <p>Стоимость, рецепты, во что собирается каждый предмет и какие герои покупают его в про-матчах.</p>
        </div>
      </div>
      <div className="row" style={{ marginBottom: "1rem" }}>
        <input className="input" placeholder="Поиск предмета" value={query} onChange={(e) => setQuery(e.target.value)} aria-label="Поиск предмета" />
        <Segmented label="Тип" value={kind} onChange={setKind} options={[{ value: "shop", label: "Магазин" }, { value: "neutral", label: "Нейтральные" }]} />
      </div>
      <ErrorBox error={error} />
      {!data && !error && <Loading what="предметов" />}
      {kind === "shop"
        ? BANDS.map((band, i) => {
            const min = i === 0 ? 0 : BANDS[i - 1]!.max;
            const group = list.filter((it) => it.cost > min && it.cost <= band.max).sort((a, b) => a.cost - b.cost);
            if (!group.length) return null;
            return (
              <section key={band.label} style={{ marginBottom: "1.25rem" }}>
                <h2>{band.label} золота</h2>
                <div className="order">
                  {group.map((it) => (
                    <ItemIcon key={it.key} itemKey={it.key} caption={<>{it.name}<br /><span className="gold">{gold(it.cost)}</span></>} />
                  ))}
                </div>
              </section>
            );
          })
        : [1, 2, 3, 4, 5].map((tier) => {
            const group = list.filter((it) => it.tier === tier);
            if (!group.length) return null;
            return (
              <section key={tier} style={{ marginBottom: "1.25rem" }}>
                <h2>Уровень {tier}</h2>
                <div className="order">
                  {group.map((it) => (
                    <ItemIcon key={it.key} itemKey={it.key} />
                  ))}
                </div>
              </section>
            );
          })}
      {kind === "neutral" && (
        <p className="source">Уровни взяты из данных предметов OpenDota. Патч 7.41 изменил набор нейтральных предметов, некоторые старые могут остаться в списке.</p>
      )}
    </>
  );
}

export function ItemPage() {
  const { key = "" } = useParams();
  const { data: item, error } = useItem(key);
  if (error) return <ErrorBox error={error} />;
  if (!item) return <Loading what="предмета" />;
  return (
    <>
      <div className="hero-title">
        <ItemIcon itemKey={item.key} link={false} caption="" />
        <div>
          <h1>{item.name}</h1>
          <p className="muted" style={{ margin: 0 }}>
            <span className="gold">{gold(item.cost)} золота</span>
            {item.recipe_cost ? `, рецепт ${gold(item.recipe_cost)}` : ""}
            {item.tier ? `, нейтральный, уровень ${item.tier}` : ""}
          </p>
        </div>
      </div>
      <div className="grid cols-2">
        <section className="panel">
          {item.attrib.length > 0 && (
            <ul className="small" style={{ paddingLeft: "1.1rem" }}>
              {item.attrib.map((a) => (
                <li key={a}>{a}</li>
              ))}
            </ul>
          )}
          {item.abilities.map((a) => (
            <div key={a.title} style={{ marginBottom: "0.75rem" }}>
              <h3 style={{ marginBottom: "0.2rem" }}>
                {a.title} <span className="tag">{a.type}</span>
              </h3>
              <p className="small" style={{ whiteSpace: "pre-line" }}>
                {a.description}
              </p>
            </div>
          ))}
          {item.notes && <p className="small muted">{item.notes}</p>}
        </section>
        <section className="panel">
          {item.components_detail.length > 0 && (
            <>
              <h3>Компоненты</h3>
              <div className="order" style={{ marginBottom: "1rem" }}>
                {item.components_detail.map((c, i) => (
                  <ItemIcon key={`${c.key}${i}`} itemKey={c.key} />
                ))}
              </div>
            </>
          )}
          {item.builds_into.length > 0 && (
            <>
              <h3>Собирается в</h3>
              <div className="order" style={{ marginBottom: "1rem" }}>
                {item.builds_into.map((c) => (
                  <ItemIcon key={c.key} itemKey={c.key} />
                ))}
              </div>
            </>
          )}
          <h3>Кто собирает его в про-матчах</h3>
          {item.bought_by.length ? (
            <table>
              <tbody>
                {item.bought_by.map((b) => (
                  <tr key={b.hero}>
                    <td>
                      <HeroChip hero={b.hero} size={22} />
                    </td>
                    <td className="num">{pct(b.share, 0)} матчей</td>
                    <td className="num muted">{clock(b.median_time)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="small muted">На этом патче не входит в основную сборку ни одного героя у про-игроков.</p>
          )}
        </section>
      </div>
      <p>
        <Link to="/items">Все предметы</Link>
      </p>
    </>
  );
}
