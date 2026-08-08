/**
 * Tabular Data tool nodes — generic CSV/Parquet analysis via DuckDB.
 *
 * Provides tools for:
 * - Listing available data files
 * - Getting table schema (column names, types, sample values)
 * - Executing SQL queries against CSV/Parquet files
 * - Sampling data rows for exploration
 *
 * Unlike the Chinook nodes which are hardcoded to one database schema,
 * these tools work with arbitrary tabular datasets (Kaggle CSVs, Parquet files).
 * The backend uses DuckDB to execute SQL directly against data files.
 */

import { Ok, Err, type Result } from '@core/kernel/Result';
import type { INodeDefinition } from '@core/model/contracts/node';
import type { AbstractNodeModel } from '@core/model/AbstractNodeModel';
import type { ExecutionContext, INodeExecutor, IToolExecutor } from '@core/execution/INodeExecutor';
import type { ToolSpec } from '@core/providers/ILLMProvider';
import { AbstractToolNodeModel, createToolExecutor, defineToolNode } from './AbstractToolNode';

/* ================================================================== *
 * List Data Files
 * ================================================================== */

export class ListDataFilesNodeModel extends AbstractToolNodeModel {}

/**
 * Lists all CSV and Parquet files available in the workflow's data directory.
 */
export const listDataFilesNode: INodeDefinition = defineToolNode(
  {
    id: 'tool.tabular-list-files',
    label: 'List Data Files',
    description: 'Lists all CSV and Parquet files available for analysis in the data directory.',
    iconId: 'node-database',
    accent: 'blue',
    keywords: ['data', 'files', 'csv', 'parquet', 'dataset', 'list'],
    defaultSize: { width: 280, height: 140 },
    fields: [],
  },
  ListDataFilesNodeModel,
);

const listDataFilesTool: IToolExecutor = {
  describeTool(): ToolSpec {
    return {
      name: 'list_data_files',
      description:
        'Returns a list of all CSV and Parquet files available in the data directory with their sizes. Call this first to discover what datasets are available.',
      parameters: {
        type: 'object',
        properties: {
          directory: {
            type: 'string',
            description: 'Subdirectory to search (default: "." for root)',
            default: '.',
          },
        },
        required: [],
        additionalProperties: false,
      },
    };
  },

  async invokeTool(
    _node: AbstractNodeModel,
    _args: Record<string, unknown>,
    ctx: ExecutionContext,
  ): Promise<Result<string, string>> {
    ctx.log('Listing available data files');
    // Backend will execute the real Python tool
    return Ok('Data files listed successfully');
  },
};

export const listDataFilesExecutor: INodeExecutor = createToolExecutor(
  listDataFilesNode.id,
  listDataFilesTool,
);

/* ================================================================== *
 * Get Table Schema
 * ================================================================== */

const FIELD_FILE_NAME = 'fileName';

export class GetTableSchemaNodeModel extends AbstractToolNodeModel {
  get fileName(): string {
    return this.getText(FIELD_FILE_NAME).trim();
  }
}

/**
 * Infers and returns the schema of a tabular data file (CSV/Parquet).
 */
export const getTableSchemaNode: INodeDefinition = defineToolNode(
  {
    id: 'tool.tabular-get-schema',
    label: 'Get Table Schema',
    description: 'Retrieves column names, data types, and sample values for a CSV or Parquet file.',
    iconId: 'node-database',
    accent: 'blue',
    keywords: ['schema', 'columns', 'types', 'csv', 'parquet', 'dataset'],
    defaultSize: { width: 280, height: 160 },
    fields: [
      {
        kind: 'text',
        key: FIELD_FILE_NAME,
        label: 'File name',
        placeholder: 'e.g., vgsales.csv',
        defaultValue: '',
        validate: (value) =>
          value.trim().endsWith('.csv') || value.trim().endsWith('.parquet')
            ? null
            : 'Must end with .csv or .parquet',
      },
    ],
  },
  GetTableSchemaNodeModel,
);

const getTableSchemaTool: IToolExecutor = {
  describeTool(node: AbstractNodeModel): ToolSpec {
    const tool = node as GetTableSchemaNodeModel;
    return {
      name: 'get_table_schema',
      description:
        'Returns the column names, data types, non-null counts, and sample values for a CSV or Parquet file. Use this to understand the structure of a dataset before querying it.',
      parameters: {
        type: 'object',
        properties: {
          fileName: {
            type: 'string',
            description: 'Name of the CSV or Parquet file (e.g., "vgsales.csv")',
            default: tool.fileName || 'vgsales.csv',
          },
        },
        required: ['fileName'],
        additionalProperties: false,
      },
    };
  },

  async invokeTool(
    node: AbstractNodeModel,
    args: Record<string, unknown>,
    ctx: ExecutionContext,
  ): Promise<Result<string, string>> {
    const tool = node as GetTableSchemaNodeModel;
    const fileName =
      (typeof args['fileName'] === 'string' && args['fileName'].trim()) || tool.fileName;

    if (!fileName) {
      return Err('No file name provided. Specify a CSV or Parquet file.');
    }

    ctx.log(`Retrieving schema for file: ${fileName}`);
    return Ok(`Schema retrieved for ${fileName}`);
  },
};

export const getTableSchemaExecutor: INodeExecutor = createToolExecutor(
  getTableSchemaNode.id,
  getTableSchemaTool,
);

/* ================================================================== *
 * Query Data
 * ================================================================== */

const FIELD_MAX_ROWS = 'maxRows';

export class QueryDataNodeModel extends AbstractToolNodeModel {
  get maxRows(): number {
    return this.getNumber(FIELD_MAX_ROWS, 200);
  }
}

/**
 * Executes SQL queries against tabular data files using DuckDB.
 */
export const queryDataNode: INodeDefinition = defineToolNode(
  {
    id: 'tool.tabular-query',
    label: 'Query Data',
    description: 'Executes a SQL query against CSV/Parquet files using DuckDB.',
    iconId: 'node-database',
    accent: 'green',
    keywords: ['sql', 'query', 'duckdb', 'csv', 'parquet', 'analyze'],
    defaultSize: { width: 320, height: 200 },
    fields: [
      {
        kind: 'slider',
        key: FIELD_MAX_ROWS,
        label: 'Max rows',
        min: 10,
        max: 1000,
        step: 10,
        defaultValue: 200,
        format: (value) => `${value}`,
      },
    ],
  },
  QueryDataNodeModel,
);

const queryDataTool: IToolExecutor = {
  describeTool(node: AbstractNodeModel): ToolSpec {
    const tool = node as QueryDataNodeModel;
    return {
      name: 'query_data',
      description:
        "Executes a SQL SELECT query against CSV/Parquet files using DuckDB. Use the file name (without extension) as the table name. Example: SELECT * FROM vgsales WHERE Genre = 'Action' LIMIT 10",
      parameters: {
        type: 'object',
        properties: {
          query: {
            type: 'string',
            description: 'SQL query to execute. Use file name (without extension) as table name.',
          },
          maxRows: {
            type: 'number',
            description: 'Maximum rows to return',
            default: tool.maxRows,
            minimum: 1,
            maximum: 1000,
          },
        },
        required: ['query'],
        additionalProperties: false,
      },
    };
  },

  async invokeTool(
    node: AbstractNodeModel,
    args: Record<string, unknown>,
    ctx: ExecutionContext,
  ): Promise<Result<string, string>> {
    const tool = node as QueryDataNodeModel;
    const query = typeof args['query'] === 'string' ? args['query'].trim() : '';
    const maxRows = typeof args['maxRows'] === 'number' ? args['maxRows'] : tool.maxRows;

    if (!query) {
      return Err('No SQL query provided');
    }

    // Validate it's a SELECT query
    const normalizedQuery = query.toUpperCase();
    if (!normalizedQuery.startsWith('SELECT') && !normalizedQuery.startsWith('WITH')) {
      return Err('Only SELECT queries are allowed for safety reasons');
    }

    ctx.log(`Executing SQL query (max ${maxRows} rows)`);
    return Ok(`Query executed successfully`);
  },
};

export const queryDataExecutor: INodeExecutor = createToolExecutor(queryDataNode.id, queryDataTool);

/* ================================================================== *
 * Sample Data
 * ================================================================== */

const FIELD_SAMPLE_FILE_NAME = 'fileName';
const FIELD_N_ROWS = 'nRows';

export class SampleDataNodeModel extends AbstractToolNodeModel {
  get fileName(): string {
    return this.getText(FIELD_SAMPLE_FILE_NAME).trim();
  }

  get nRows(): number {
    return this.getNumber(FIELD_N_ROWS, 10);
  }
}

/**
 * Returns a sample of rows from a data file for quick exploration.
 */
export const sampleDataNode: INodeDefinition = defineToolNode(
  {
    id: 'tool.tabular-sample',
    label: 'Sample Data',
    description:
      'Returns a preview sample of rows from a CSV or Parquet file for quick exploration.',
    iconId: 'node-database',
    accent: 'orange',
    keywords: ['sample', 'preview', 'rows', 'csv', 'parquet', 'explore'],
    defaultSize: { width: 280, height: 180 },
    fields: [
      {
        kind: 'text',
        key: FIELD_SAMPLE_FILE_NAME,
        label: 'File name',
        placeholder: 'e.g., vgsales.csv',
        defaultValue: '',
        validate: (value) =>
          value.trim().endsWith('.csv') || value.trim().endsWith('.parquet')
            ? null
            : 'Must end with .csv or .parquet',
      },
      {
        kind: 'slider',
        key: FIELD_N_ROWS,
        label: 'Rows',
        min: 5,
        max: 50,
        step: 5,
        defaultValue: 10,
        format: (value) => `${value}`,
      },
    ],
  },
  SampleDataNodeModel,
);

const sampleDataTool: IToolExecutor = {
  describeTool(node: AbstractNodeModel): ToolSpec {
    const tool = node as SampleDataNodeModel;
    return {
      name: 'sample_data',
      description:
        'Returns a preview sample of rows from a CSV or Parquet file. Use this to quickly see what the data looks like before writing queries.',
      parameters: {
        type: 'object',
        properties: {
          fileName: {
            type: 'string',
            description: 'Name of the CSV or Parquet file to sample',
            default: tool.fileName || 'vgsales.csv',
          },
          nRows: {
            type: 'number',
            description: 'Number of rows to sample (max 50)',
            default: tool.nRows,
            minimum: 1,
            maximum: 50,
          },
        },
        required: ['fileName'],
        additionalProperties: false,
      },
    };
  },

  async invokeTool(
    node: AbstractNodeModel,
    args: Record<string, unknown>,
    ctx: ExecutionContext,
  ): Promise<Result<string, string>> {
    const tool = node as SampleDataNodeModel;
    const fileName =
      (typeof args['fileName'] === 'string' && args['fileName'].trim()) || tool.fileName;
    const nRows = typeof args['nRows'] === 'number' ? args['nRows'] : tool.nRows;

    if (!fileName) {
      return Err('No file name provided. Specify a CSV or Parquet file.');
    }

    if (nRows < 1 || nRows > 50) {
      return Err('nRows must be between 1 and 50');
    }

    ctx.log(`Sampling ${nRows} rows from ${fileName}`);
    return Ok(`Sampled ${nRows} rows from ${fileName}`);
  },
};

export const sampleDataExecutor: INodeExecutor = createToolExecutor(
  sampleDataNode.id,
  sampleDataTool,
);

/* ================================================================== *
 * Export all tabular data nodes
 * ================================================================== */

export const TABULAR_NODES = [
  { definition: listDataFilesNode, executor: listDataFilesExecutor },
  { definition: getTableSchemaNode, executor: getTableSchemaExecutor },
  { definition: queryDataNode, executor: queryDataExecutor },
  { definition: sampleDataNode, executor: sampleDataExecutor },
];
