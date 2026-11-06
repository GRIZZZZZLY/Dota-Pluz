import { useState } from "react";
import { useMeta } from "../api/hooks";
import { ErrorBox, HeroChip, Loading, Segmented } from "../components/common";
import { MEDALS, POSITION_NAMES, dateTime, pct } from "../lib/format";

export function MetaPage() {
  const [source, setSource] = useState("bracket");
  const [bracket, setBracket] = useState<number | null>(null);
  const [position, setPosition] = useState<number | null>(null);
  const { data, error, isFetching } = useMeta(source, bracket, position);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Мета</h1>
          <p>Винрейты на текущем патче. Тиры — диапазоны винрейта: верхняя десятая часть — S, нижняя пятая — D.</p>
        </div>
      </div>
      <div className="stack" style={{ marginBottom: "1rem" }}>
        <Segmented
          label="Источник"
          value={source}
          onChange={setSource}
          options={[
            { value: "bracket", label: "Публичные по медалям" },
            { value: "matrix", label: "Выборка Ranked All Pick" },
            { value: "pro", label: "Про-матчи" },
            { value: "turbo", label: "Турбо" },
          ]}
        />
        {source === "bracket" && (
          <Segmented
            label="Медаль"
            value={bracket ?? 0}
            onChange={(v) => setBracket(v || null)}
            options={[{ value: 0, label: "Все медали" }, ...MEDALS.map((m, i) => ({ value: i + 1, label: m }))]}
          />
        )}
        <Segmented
          label="Позиция"
          value={position ?? 0}
          onChange={(v) => setPosition(v || null)}
          options={[{ value: 0, label: "Любая позиция" }, ...[1, 2, 3, 4, 5].map((p) => ({ value: p, label: POSITION_NAMES[p]! }))]}
        />
      </div>
      <ErrorBox error={error} />
      {!data && !error && <Loading what="меты" />}
      {data && (
        <section className="panel" style={{ opacity: isFetching ? 0.6 : 1 }}>
          <table>
            <thead>
              <tr>
                <th>Тир</th>
                <th>Герой</th>
                <th className="num">Винрейт</th>
                <th className="num">Матчи</th>
                <th className="num">Доля пиков</th>
                {source === "pro" && <th className="num">Баны</th>}
                <th>Позиции</th>
              </tr>
            </thead>
            <tbody>
              {data.rows.map((r) => (
                <tr key={r.hero}>
                  <td className={`tier ${r.tier}`}>{r.tier}</td>
                  <td>
                    <HeroChip hero={r.hero} size={26} />
                  </td>
                  <td className="num">{pct(r.win_rate)}</td>
                  <td className="num">{r.picks.toLocaleString("ru-RU")}</td>
                  <td className="num muted">{pct(r.pick_share)}</td>
                  {source === "pro" && <td className="num">{r.bans}</td>}
                  <td className="small muted">{r.positions.join(", ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="source">
            {data.data_source ?? "OpenDota"}, обновлено {dateTime(data.generated_at)}. Герои с долей пиков меньше 0,5% не показаны.
          </p>
        </section>
      )}
    </>
  );
}
