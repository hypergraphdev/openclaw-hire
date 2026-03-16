import { NavLink } from "react-router-dom";

const links = [
  { to: "/", label: "Register" },
  { to: "/hire", label: "Hire" },
  { to: "/employees", label: "Employees" },
];

export function NavBar() {
  return (
    <div className="border-b border-ink/10 px-6 py-4 md:px-8">
      <div className="flex flex-wrap gap-3">
        {links.map((link) => (
          <NavLink
            key={link.to}
            to={link.to}
            className={({ isActive }) =>
              `rounded-full px-4 py-2 text-sm font-medium transition ${
                isActive ? "bg-ink text-sand" : "bg-sand text-ink hover:bg-ember hover:text-white"
              }`
            }
          >
            {link.label}
          </NavLink>
        ))}
      </div>
    </div>
  );
}
