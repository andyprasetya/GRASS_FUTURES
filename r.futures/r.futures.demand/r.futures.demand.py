#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
##############################################################################
#
# MODULE:       r.futures.demand
#
# AUTHOR(S):    Anna Petrasova (kratochanna gmail.com)
#
# PURPOSE:      create demand table for FUTURES
#
# COPYRIGHT:    (C) 2015 by the GRASS Development Team
#
#		This program is free software under the GNU General Public
#		License (version 2). Read the file COPYING that comes with GRASS
#		for details.
#
##############################################################################

#%module
#% description: Script for creating demand table which determines the quantity of land change expected.
#% keyword: raster
#% keyword: demand
#%end
#%option G_OPT_R_INPUTS
#% key: development
#% description: Names of input binary raster maps representing development
#% guisection: Input maps
#%end
#%option G_OPT_R_INPUT
#% key: subregions
#% description: Raster map of subregions
#% guisection: Input maps
#%end
#%option G_OPT_F_INPUT
#% key: observed_population
#% description: CSV file with observed population in subregions at certain times
#% guisection: Input population
#%end
#%option G_OPT_F_INPUT
#% key: projected_population
#% description: CSV file with projected population in subregions at certain times
#% guisection: Input population
#%end
#%option
#% type: integer
#% key: simulation_times
#% multiple: yes
#% required: yes
#% description: For which times demand is projected
#% guisection: Output
#%end
#%option
#% type: string
#% key: method
#% multiple: yes
#% required: yes
#% description: Relationship between developed cells (dependent) and population (explanatory)
#% options: linear, logarithmic, exponential
#% descriptions:linear;y = A + Bx;logarithmic;y = A + Bln(x);exponential;y = Ae^(BX)
#% answer: linear,logarithmic
#% guisection: Optional
#%end
#%option G_OPT_F_OUTPUT
#% key: plot
#% required: no
#% description: Save plotted relationship between developed cells and population into a file
#% guisection: Output
#%end
#%option G_OPT_F_OUTPUT
#% key: demand
#% description: Output CSV file with demand (times as rows, regions as columns)
#% guisection: Output
#%end
#%option G_OPT_F_SEP
#% label: Separator used in input CSV files
#% guisection: Input population
#%end


import sys
import numpy as np

import grass.script.core as gcore
import grass.script.utils as gutils


def main():
    developments = options['development'].split(',')
    observed_popul_file = options['observed_population']
    projected_popul_file = options['projected_population']
    sep = gutils.separator(options['separator'])
    subregions = options['subregions']
    methods = options['method'].split(',')
    plot = options['plot']
    simulation_times = [float(each) for each in options['simulation_times'].split(',')]

    observed_popul = np.genfromtxt(observed_popul_file, dtype=float, delimiter=sep, names=True)
    projected_popul = np.genfromtxt(projected_popul_file, dtype=float, delimiter=sep, names=True)
    year_col = observed_popul.dtype.names[0]
    observed_times = observed_popul[year_col]
    year_col = projected_popul.dtype.names[0]
    projected_times = projected_popul[year_col]

    if len(developments) != len(observed_times):
        gcore.fatal(_("Number of development raster maps doesn't not correspond to the number of observed times"))

    # gather developed cells in subregions
    gcore.info(_("Computing number of developed cells..."))
    table_developed = {}
    subregionIds = set()
    for i in range(len(observed_times)):
        gcore.percent(i, len(observed_times), 1)
        data = gcore.read_command('r.univar', flags='gt', zones=subregions, map=developments[i])
        for line in data.splitlines():
            stats = line.split('|')
            if stats[0] == 'zone':
                continue
            subregionId, developed_cells = stats[0], int(stats[12])
            subregionIds.add(subregionId)
            if i == 0:
                table_developed[subregionId] = []
            table_developed[subregionId].append(developed_cells)
        gcore.percent(1, 1, 1)
    subregionIds = sorted(list(subregionIds))
    # linear interpolation between population points
    population_for_simulated_times = {}
    for subregionId in table_developed.keys():
        population_for_simulated_times[subregionId] = np.interp(x=simulation_times,
                                                                xp=np.append(observed_times, projected_times),
                                                                fp=np.append(observed_popul[subregionId],
                                                                             projected_popul[subregionId]))
    # regression
    demand = {}
    i = 0
    if plot:
        import matplotlib.pyplot as plt
        n_plots = np.ceil(np.sqrt(len(subregionIds)))
        fig = plt.figure(figsize=(5 * n_plots, 5 * n_plots))

    for subregionId in subregionIds:
        i += 1
        rmse = dict()
        predicted = dict()
        simulated = dict()
        coeff = dict()
        for method in methods:
            # observed population points for subregion
            reg_pop = observed_popul[subregionId]
            if method == 'logarithmic':
                reg_pop = np.log(reg_pop)
            if method == 'exponential':
                y = np.log(table_developed[subregionId])
            else:
                y = table_developed[subregionId]
            A = np.vstack((reg_pop, np.ones(len(reg_pop)))).T
            m, c = np.linalg.lstsq(A, y)[0]  # y = mx + c
            coeff[method] = m, c
            simulated[method] = np.array(population_for_simulated_times[subregionId])
            if method == 'logarithmic':
                predicted[method] = np.log(simulated[method]) * m + c
                r = (reg_pop * m + c) - table_developed[subregionId]
            elif method == 'exponential':
                predicted[method] = np.exp(m * simulated[method] + c)
                r = np.exp(m * reg_pop + c) - table_developed[subregionId]
            else:  # linear
                predicted[method] = simulated[method] * m + c
                r = (reg_pop * m + c) - table_developed[subregionId]
            # RMSE
            rmse[method] = np.sqrt((np.sum(r * r) / (len(reg_pop) - 2)))

        method = min(rmse, key=rmse.get)
        # write demand
        demand[subregionId] = predicted[method]
        demand[subregionId] = np.diff(demand[subregionId])
        if np.any(demand[subregionId] < 0):
            gcore.warning(_("Subregion {sub} has negative numbers"
                            " of newly developed cells, changing to zero".format(sub=subregionId)))
            demand[subregionId][demand[subregionId] < 0] = 0
        if m < 0:
            demand[subregionId].fill(0)
            gcore.warning(_("For subregion {sub} population and development are inversely proportional,"
                            "will result in zero demand".format(sub=subregionId)))

        # draw
        if plot:
            ax = fig.add_subplot(n_plots, n_plots, i)
            ax.set_title(subregionId + ', RMSE: ' + str(rmse[method]))
            ax.set_xlabel('population')
            ax.set_ylabel('developed cells')
            # plot known points
            x = np.array(observed_popul[subregionId])
            y = np.array(table_developed[subregionId])
            ax.plot(x, y, marker='o', linestyle='', markersize=8)
            # plot predicted curve
            x_pred = np.linspace(np.min(x),
                                 np.max(np.array(population_for_simulated_times[subregionId])), 10)
            m, c = coeff[method]
            if method == 'linear':
                line = x_pred * m + c
                label = "$y = {c:.3f} + {m:.3f} x$".format(m=m, c=c)
            elif method == 'logarithmic':
                line = np.log(x_pred) * m + c
                label = "$y = {c:.3f} + {m:.3f} \ln(x)$".format(m=m, c=c)
            else:
                line = np.exp(x_pred * m + c)
                label = "$y = {c:.3f} e^{{{m:.3f}x}}$".format(m=m, c=np.exp(c))
            ax.plot(x_pred, line, label=label)
            ax.plot(simulated[method], predicted[method], linestyle='', marker='o', markerfacecolor='None')
            plt.legend(loc=0)
            labels = ax.get_xticklabels()
            plt.setp(labels, rotation=30)
    if plot:
        plt.tight_layout()
        fig.savefig(plot)

    # write demand
    with open(options['demand'], 'w') as f:
        f.write('Years_to_simulate: {sim}\n'.format(sim=len(simulation_times)))
        header = observed_popul.dtype.names  # the order is kept here
        f.write('\t'.join(header))
        f.write('\n')
        i = 0
        for time in simulation_times[1:]:
            f.write(str(int(time)))
            f.write('\t')
            # put 0 where there are more counties but are not in region
            for sub in header[1:]:  # to keep order of subregions
                if sub not in subregionIds:
                    f.write('0')
                else:
                    f.write(str(int(demand[sub][i])))
                if sub != header[-1]:
                    f.write('\t')
            f.write('\n')
            i += 1


if __name__ == "__main__":
    options, flags = gcore.parser()
    sys.exit(main())
