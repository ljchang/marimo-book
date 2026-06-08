"""Package whose submodule imports the package itself (alias-cycle regression).

Mirrors py-feat's ``feat.utils.io`` doing ``import feat``: Griffe surfaces the
import as a resolvable *alias* module member, which naive submodule recursion
would follow back into the package — an infinite cycle.
"""
