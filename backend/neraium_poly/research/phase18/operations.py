"""Owner-authorized hard budgets, separate advisory storage tiers, no retention authority."""


def tier_allocations(service):
    unit=1024**3
    if service=='collector':
        return {'active':unit,'warm':40*unit,'cold':100*unit,'catalog_state':43*unit,'protected':16*unit}
    if service=='experimental':
        return {'active':unit//2,'warm':20*unit,'cold':48*unit,'catalog_state':47*unit//2,'protected':8*unit}
    raise ValueError('known approved service required')
