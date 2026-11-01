import {
  createSortedRowModel,
  rowSortingFeature,
  type SortingState,
  sortFns,
  tableFeatures,
  useTable,
} from "@tanstack/react-table";
import { ArrowDown, ArrowUp } from "lucide-react";
import { type ReactNode, useState } from "react";
import { cn } from "@/lib/utils";
import { Help } from "./Panel";

export interface Column<T> {
  id: string;
  header: ReactNode;
  cell: (row: T) => ReactNode;
  /** what the column sorts by; without it, it doesn't sort */
  sort?: (row: T) => number | string | null | undefined;
  numeric?: boolean;
  help?: ReactNode;
  /** hidden below 640 px, where tables keep the two or three numbers that matter */
  wide?: boolean;
}

interface Props<T> {
  rows: readonly T[];
  columns: ReadonlyArray<Column<T>>;
  rowKey: (row: T) => string;
  label: string;
  limit?: number;
  initialSort?: { id: string; desc: boolean } | null;
  onRowClick?: (row: T) => void;
  selected?: string | undefined;
  empty?: ReactNode;
}

const features = tableFeatures({
  rowSortingFeature,
  sortedRowModel: createSortedRowModel(),
  sortFns,
});

/** A sortable table: dense rows, numbers right-aligned in tabular figures, a "show all"
 * past `limit`, and the row click that opens what the row is about. */
export function DataTable<T extends object>({
  rows,
  columns,
  rowKey,
  label,
  limit = 25,
  initialSort = null,
  onRowClick,
  selected,
  empty,
}: Props<T>) {
  const [sorting, setSorting] = useState<SortingState>(initialSort ? [initialSort] : []);
  const [all, setAll] = useState(false);
  const table = useTable<typeof features, T>(
    {
      features,
      data: [...rows],
      columns: columns.map((column) => ({
        id: column.id,
        accessorFn: (row: T) => column.sort?.(row) ?? null,
        enableSorting: Boolean(column.sort),
        sortFn: "basic" as const,
        sortUndefined: "last" as const,
      })),
      state: { sorting },
      onSortingChange: setSorting,
      getRowId: (row: T) => rowKey(row),
    },
    (state) => ({ sorting: state.sorting }),
  );
  if (rows.length === 0)
    return <>{empty ?? <p className="px-4 pb-4 text-sm text-ink-muted">Nothing here.</p>}</>;

  const sorted = table.getRowModel().rows;
  const shown = all ? sorted : sorted.slice(0, limit);
  const byId = new Map(columns.map((column) => [column.id, column]));

  return (
    <div>
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-sm" aria-label={label}>
          <thead>
            <tr className="border-y border-border bg-surface-sunken">
              {table.getHeaderGroups()[0]?.headers.map((header) => {
                const column = byId.get(header.column.id);
                if (!column) return null;
                const direction = header.column.getIsSorted();
                return (
                  <th
                    key={header.id}
                    scope="col"
                    aria-sort={
                      direction === "asc"
                        ? "ascending"
                        : direction === "desc"
                          ? "descending"
                          : undefined
                    }
                    className={cn(
                      "h-8 px-3 text-left text-xs font-medium whitespace-nowrap text-ink-muted",
                      column.numeric && "text-right",
                      column.wide && "hidden sm:table-cell",
                    )}
                  >
                    <span
                      className={cn(
                        "inline-flex items-center gap-1",
                        column.numeric && "flex-row-reverse",
                      )}
                    >
                      {column.sort ? (
                        <button
                          type="button"
                          className="inline-flex items-center gap-0.5 hover:text-ink"
                          onClick={header.column.getToggleSortingHandler()}
                        >
                          {column.header}
                          {direction === "asc" && <ArrowUp className="size-3" />}
                          {direction === "desc" && <ArrowDown className="size-3" />}
                        </button>
                      ) : (
                        column.header
                      )}
                      {column.help && <Help>{column.help}</Help>}
                    </span>
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {shown.map((row) => {
              const key = row.id;
              return (
                <tr
                  key={key}
                  className={cn(
                    "border-b border-border last:border-b-0",
                    onRowClick && "cursor-pointer hover:bg-surface-hover",
                    selected === key && "bg-primary-wash",
                  )}
                  onClick={onRowClick ? () => onRowClick(row.original) : undefined}
                >
                  {columns.map((column) => (
                    <td
                      key={column.id}
                      className={cn(
                        "h-8 px-3 py-1.5 align-middle",
                        column.numeric && "text-right tabular-nums",
                        column.wide && "hidden sm:table-cell",
                      )}
                    >
                      {column.cell(row.original)}
                    </td>
                  ))}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {sorted.length > limit && (
        <div className="border-t border-border px-3 py-1.5">
          <button
            type="button"
            className="text-xs text-primary hover:underline"
            onClick={() => setAll(!all)}
          >
            {all ? "Show fewer" : `Show all ${sorted.length}`}
          </button>
        </div>
      )}
    </div>
  );
}
