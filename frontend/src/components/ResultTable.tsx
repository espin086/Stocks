import { useMemo, useState } from "react";
import {
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  useReactTable,
  type SortingState,
} from "@tanstack/react-table";
import { Button } from "./ui/button";
import { download, formatCell, toCsv } from "@/lib/format";

type Row = Record<string, unknown>;

/** Every table's rows are downloadable as CSV: a picture is never the only representation. */
export function ResultTable({ columns, rows, name = "result" }: { columns: string[]; rows: Row[]; name?: string }) {
  const [sorting, setSorting] = useState<SortingState>([]);
  const helper = createColumnHelper<Row>();
  const defs = useMemo(
    () =>
      columns.map((c) =>
        helper.accessor((row) => row[c], {
          id: c,
          header: c,
          cell: (info) => formatCell(info.getValue()),
        }),
      ),
    [columns, helper],
  );
  const table = useReactTable({
    data: rows,
    columns: defs,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });
  return (
    <div>
      <div className="mb-2 flex items-center justify-between text-xs text-fg-muted">
        <span>{rows.length} rows</span>
        <Button variant="ghost" onClick={() => download(`${name}.csv`, toCsv(columns, rows))}>
          Download CSV
        </Button>
      </div>
      <div className="overflow-x-auto rounded border border-border">
        <table className="w-full text-sm" aria-label={name}>
          <thead className="bg-bg text-left">
            {table.getHeaderGroups().map((hg) => (
              <tr key={hg.id}>
                {hg.headers.map((h) => (
                  <th key={h.id} className="cursor-pointer px-2 py-1 font-medium" onClick={h.column.getToggleSortingHandler()}>
                    {flexRender(h.column.columnDef.header, h.getContext())}
                    {{ asc: " ▲", desc: " ▼" }[h.column.getIsSorted() as string] ?? ""}
                  </th>
                ))}
              </tr>
            ))}
          </thead>
          <tbody>
            {table.getRowModel().rows.map((r) => (
              <tr key={r.id} className="border-t border-border">
                {r.getVisibleCells().map((c) => (
                  <td key={c.id} className="whitespace-nowrap px-2 py-1 tabular-nums">
                    {flexRender(c.column.columnDef.cell, c.getContext())}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
