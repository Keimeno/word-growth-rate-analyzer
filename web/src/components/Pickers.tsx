import { Check, ChevronsUpDown } from "lucide-react";
import { type ReactNode, useState } from "react";
import type { Meta } from "@/api/generated/model";
import { Button } from "@/components/ui/button";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { KIND_LABELS } from "@/lib/kinds";
import { cn } from "@/lib/utils";

/** A labelled control in a page's filter row. */
export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex max-w-full min-w-0 items-center gap-2">
      <span className="text-xs font-medium whitespace-nowrap text-ink-muted">{label}</span>
      {children}
    </div>
  );
}

/** One of a few options, all visible: a window, a range. */
export function Segmented<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: T;
  options: ReadonlyArray<readonly [T, string]>;
  onChange: (value: T) => void;
}) {
  return (
    <ToggleGroup
      type="single"
      variant="outline"
      size="sm"
      aria-label={label}
      value={value}
      onValueChange={(next) => {
        if (next) onChange(next as T);
      }}
    >
      {options.map(([key, text]) => (
        <ToggleGroupItem key={key} value={key}>
          {text}
        </ToggleGroupItem>
      ))}
    </ToggleGroup>
  );
}

/** Several of many: kinds of terms, in a popover with what's picked on the trigger; at
 * least one stays picked. */
export function KindChips({
  kinds,
  value,
  onChange,
}: {
  kinds: readonly string[];
  value: readonly string[];
  onChange: (value: string[]) => void;
}) {
  const [open, setOpen] = useState(false);
  const label = (kind: string) => KIND_LABELS[kind] ?? kind;
  const all = kinds.every((kind) => value.includes(kind));
  const summary = all
    ? `All ${kinds.length}`
    : value.length <= 2
      ? value.map(label).join(", ")
      : `${value.length} of ${kinds.length}`;
  const toggle = (kind: string) => {
    const next = value.includes(kind) ? value.filter((item) => item !== kind) : [...value, kind];
    if (next.length) onChange(kinds.filter((item) => next.includes(item)));
  };
  return (
    <Field label="Kinds">
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button
            variant="outline"
            aria-label={`Kinds of terms: ${summary}`}
            className="max-w-60 justify-between gap-2 px-2.5 font-normal"
          >
            <span className="truncate">{summary}</span>
            <ChevronsUpDown className="size-3.5 text-ink-muted" />
          </Button>
        </PopoverTrigger>
        <PopoverContent className="w-56 p-0" align="start">
          <Command>
            <CommandList>
              <CommandGroup>
                <CommandItem onSelect={() => onChange([...kinds])}>
                  <Check className={cn("size-3.5", all ? "opacity-100" : "opacity-0")} />
                  All kinds
                </CommandItem>
                {kinds.map((kind) => (
                  <CommandItem
                    key={kind}
                    value={`${kind} ${label(kind)}`}
                    onSelect={() => toggle(kind)}
                  >
                    <Check
                      className={cn("size-3.5", value.includes(kind) ? "opacity-100" : "opacity-0")}
                    />
                    {label(kind)}
                  </CommandItem>
                ))}
              </CommandGroup>
            </CommandList>
          </Command>
        </PopoverContent>
      </Popover>
    </Field>
  );
}

/** Any number of many, in a searchable popover; none picked means all. */
export function MultiPicker({
  label,
  allLabel,
  options,
  value,
  onChange,
}: {
  label: string;
  allLabel: string;
  options: ReadonlyArray<readonly [string, string]>;
  value: readonly string[];
  onChange: (value: string[]) => void;
}) {
  const [open, setOpen] = useState(false);
  const names = new Map(options);
  const summary =
    value.length === 0
      ? allLabel
      : value.length === 1
        ? (names.get(value[0] ?? "") ?? value[0])
        : `${value.length} picked`;
  const toggle = (key: string) =>
    onChange(value.includes(key) ? value.filter((item) => item !== key) : [...value, key]);
  return (
    <Field label={label}>
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button variant="outline" className="max-w-56 justify-between gap-2 px-2.5 font-normal">
            <span className="truncate">{summary}</span>
            <ChevronsUpDown className="size-3.5 text-ink-muted" />
          </Button>
        </PopoverTrigger>
        <PopoverContent className="w-64 p-0" align="start">
          <Command>
            {options.length > 8 && <CommandInput placeholder={`Find ${label.toLowerCase()}…`} />}
            <CommandList>
              <CommandEmpty>Nothing matches.</CommandEmpty>
              <CommandGroup>
                <CommandItem onSelect={() => onChange([])}>
                  <Check className={cn("size-3.5", value.length ? "opacity-0" : "opacity-100")} />
                  {allLabel}
                </CommandItem>
                {options.map(([key, text]) => (
                  <CommandItem key={key} value={`${key} ${text}`} onSelect={() => toggle(key)}>
                    <Check
                      className={cn("size-3.5", value.includes(key) ? "opacity-100" : "opacity-0")}
                    />
                    {text}
                  </CommandItem>
                ))}
              </CommandGroup>
            </CommandList>
          </Command>
        </PopoverContent>
      </Popover>
    </Field>
  );
}

const TYPES = { platform: "Platforms", group: "Groups", channel: "Channels" } as const;

/** A platform, group or channel, grouped like that, with each group's members. */
export function ScopePicker({
  meta,
  value,
  onChange,
}: {
  meta: Meta | undefined;
  value: string;
  onChange: (scope: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const scopes = meta?.scopes ?? [];
  const groups = meta?.groups ?? {};
  const members = groups[value];
  return (
    <Field label="Scope">
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button
            variant="outline"
            aria-label={`Scope: ${value}`}
            className="max-w-72 justify-between gap-2 px-2.5 font-normal"
          >
            <span className="truncate">
              <span className="font-medium">{value}</span>
              {members && <span className="text-ink-muted"> · {members.length} channels</span>}
            </span>
            <ChevronsUpDown className="size-3.5 text-ink-muted" />
          </Button>
        </PopoverTrigger>
        <PopoverContent className="w-72 p-0" align="start">
          <Command>
            <CommandInput placeholder="Find a platform, group or channel…" />
            <CommandList>
              <CommandEmpty>No such scope.</CommandEmpty>
              {(Object.keys(TYPES) as Array<keyof typeof TYPES>).map((type) => {
                const ofType = scopes.filter((scope) => scope.type === type);
                if (!ofType.length) return null;
                return (
                  <CommandGroup key={type} heading={TYPES[type]}>
                    {ofType.map((scope) => (
                      <CommandItem
                        key={scope.name}
                        value={`${scope.name} ${(groups[scope.name] ?? []).join(" ")}`}
                        onSelect={() => {
                          onChange(scope.name);
                          setOpen(false);
                        }}
                      >
                        <Check
                          className={cn(
                            "size-3.5",
                            scope.name === value ? "opacity-100" : "opacity-0",
                          )}
                        />
                        <span className="truncate">{scope.name}</span>
                        {groups[scope.name] && (
                          <span className="ml-auto text-xs text-ink-muted">
                            {groups[scope.name]?.length}
                          </span>
                        )}
                      </CommandItem>
                    ))}
                  </CommandGroup>
                );
              })}
            </CommandList>
          </Command>
        </PopoverContent>
      </Popover>
    </Field>
  );
}

/** A group and its channels, for the tables of trends: "In" the group or some channels. */
export function scopeOptions(meta: Meta | undefined, scope: string): Array<[string, string]> {
  const channels = meta?.groups[scope] ?? [];
  return [
    [scope, `${scope} overall`],
    ...channels.map((channel): [string, string] => [channel, channel]),
  ];
}
